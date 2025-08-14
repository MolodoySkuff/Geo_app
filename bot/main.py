import os
import json
import asyncio
import logging
from dotenv import load_dotenv

from shapely.geometry import shape, Point, Polygon
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot import states
from .services import geocoding, osm, dem, metrics, pdf, map_render
from .storage.cache import ensure_dirs
from .providers.external import get_geometry_by_cadnum

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://localhost:8080")
EXTERNAL_GEOM_PROVIDER = os.getenv("EXTERNAL_GEOM_PROVIDER", "off") == "on"

# Инициализация бота/DP/роутера
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)
ensure_dirs()

def main_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Открыть карту", web_app=WebAppInfo(url=WEBAPP_URL)),
         InlineKeyboardButton(text="📄 Загрузить GeoJSON/KML", callback_data="upload_help")],
        [InlineKeyboardButton(text="📍 Точка + площадь", callback_data="point_area"),
         InlineKeyboardButton(text="🔎 КН → контур", callback_data="cadnum")],
        [InlineKeyboardButton(text="📊 Компаративы", callback_data="comps")]
    ])
    return kb

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(m: types.Message):
    await m.answer(
        "Гео‑скоринг участков: нарисуйте полигон или пришлите GeoJSON/KML. "
        "Подтянем OSM/DEM, посчитаем уклон, доступность, близость к воде/дорогам и сделаем PDF.",
        reply_markup=main_keyboard()
    )

@router.callback_query(F.data == "upload_help")
async def upload_help(c: types.CallbackQuery):
    await c.message.answer("Пришлите файл .geojson или .kml как документ. Можно несколько.")
    await c.answer()

@router.callback_query(F.data == "point_area")
async def point_area_start(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(states.PointArea.waiting_location)
    await c.message.answer("Отправьте геопозицию 📍 (кнопкой в чате).")
    await c.answer()

@router.message(StateFilter(states.PointArea.waiting_location), F.location)
async def point_area_loc(m: types.Message, state: FSMContext):
    await state.update_data(lat=m.location.latitude, lon=m.location.longitude)
    await state.set_state(states.PointArea.waiting_area)
    await m.answer("Введите требуемую площадь в сотках (например, 10).")

@router.message(StateFilter(states.PointArea.waiting_area))
async def point_area_area(m: types.Message, state: FSMContext):
    try:
        area_sot = float(m.text.replace(",", "."))
        data = await state.get_data()
        lat, lon = data["lat"], data["lon"]
        poly = metrics.square_from_point_area(lat, lon, area_sot)
        await state.clear()
        await run_pipeline_and_reply(m, poly, source="point+area")
    except Exception as e:
        await m.answer(f"Ошибка: {e}. Попробуйте снова или /start")
        await state.clear()

@router.callback_query(F.data == "cadnum")
async def cadnum_start(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(states.Cadnum.waiting_text)
    await c.message.answer("Введите кадастровый номер (формат 77:XX:XXXXXXX:XXX)")
    await c.answer()

@router.message(StateFilter(states.Cadnum.waiting_text))
async def cadnum_handle(m: types.Message, state: FSMContext):
    cad = m.text.strip()
    geom = None
    if EXTERNAL_GEOM_PROVIDER:
        geom = await asyncio.to_thread(get_geometry_by_cadnum, cad)
    if geom is None:
        await m.answer("Пока нет подключённого провайдера КН→контур. Нарисуйте участок на карте или пришлите GeoJSON.")
    else:
        await run_pipeline_and_reply(m, geom, source=f"cadnum:{cad}")
    await state.clear()

@router.message(F.document)
async def doc_handler(m: types.Message):
    doc = m.document
    dest_dir = "cache/uploads"
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{doc.file_id}_{doc.file_name or 'upload'}"
    path = os.path.join(dest_dir, filename)
    try:
        await bot.download(doc, destination=path)
        poly = metrics.read_polygon_from_file(path)
        await run_pipeline_and_reply(m, poly, source=os.path.basename(path))
    except Exception as e:
        await m.answer(f"Не удалось прочитать геометрию из файла: {e}")

@router.message(F.web_app_data)
async def webapp_data(m: types.Message):
    try:
        payload = json.loads(m.web_app_data.data)
        if "type" in payload and payload["type"] == "Feature" and "geometry" in payload:
            g = shape(payload["geometry"])
        elif "type" in payload and payload["type"] in ("Polygon", "MultiPolygon"):
            g = shape(payload)
        else:
            raise ValueError("Ожидался GeoJSON Feature/Polygon")
        await run_pipeline_and_reply(m, g, source="webapp")
    except Exception as e:
        await m.answer(f"Ошибка WebApp данных: {e}")

@router.callback_query(F.data == "comps")
async def comps_start(c: types.CallbackQuery, state: FSMContext):
    await state.set_state(states.Comps.collecting)
    await c.message.answer("Пришлите 2–5 строк:\nплощадь_соток; цена_₽; ссылка(опц.)\nКогда готово — /done")
    await c.answer()

@router.message(StateFilter(states.Comps.collecting), Command("done"))
async def comps_done(m: types.Message, state: FSMContext):
    data = await state.get_data()
    rows = data.get("rows", [])
    if len(rows) < 2:
        await m.answer("Нужно минимум 2 сравнимых.")
        return
    # Простейшая вилка
    pps = sorted([r["pp_sot"] for r in rows if r.get("pp_sot")])
    mid = pps[len(pps)//2] if pps else None
    if mid:
        await m.answer(f"Оценка по компаративам (средняя цена за сотку): ~{int(mid):,} ₽/сот.".replace(",", " "))
    await m.answer("Готово. В PDF появится раздел “Компаративы” (в следующей версии).")
    await state.clear()

@router.message(StateFilter(states.Comps.collecting))
async def comps_collect(m: types.Message, state: FSMContext):
    txt = m.text.strip()
    parts = [p.strip() for p in txt.split(";")]
    try:
        area_sot = float(parts[0].replace(",", ".").replace(" ", ""))
        price = float(parts[1].replace(" ", ""))
        link = parts[2] if len(parts) > 2 else ""
    except Exception:
        await m.answer("Формат: площадь_соток; цена_₽; ссылка(опц.)")
        return
    rows = (await state.get_data()).get("rows", [])
    rows.append({"area_sot": area_sot, "price": price, "link": link, "pp_sot": price / max(area_sot, 0.0001)})
    await state.update_data(rows=rows)
    await m.answer(f"Принято. Сейчас {len(rows)} записей. /done для завершения.")

async def run_pipeline_and_reply(m: types.Message, geom_wgs84, source: str = ""):
    await m.answer("Обрабатываем участок… это займёт ~5–20 секунд.")
    # 1) Адрес
    centroid = geom_wgs84.centroid
    addr = await asyncio.to_thread(geocoding.reverse_geocode, centroid.y, centroid.x)
    # 2) OSM по bbox
    bbox = metrics.expand_bbox(geom_wgs84.bounds, meters=2000)
    osm_data = await asyncio.to_thread(osm.fetch_overpass, bbox)
    # 3) DEM/уклон
    dem_stats = await asyncio.to_thread(dem.compute_dem_stats, geom_wgs84)
    # 4) Метрики
    metric_set = await asyncio.to_thread(metrics.compute_all, geom_wgs84, osm_data, dem_stats)
    # 5) Статичная карта
    map_path = await asyncio.to_thread(map_render.render_static_map, geom_wgs84, osm_data, "cache/maps")
    # 6) PDF
    pdf_path = await asyncio.to_thread(pdf.render_report, metric_set, addr, source, map_path)

    text = metrics.format_brief(metric_set, addr)
    await m.answer_photo(photo=FSInputFile(map_path), caption=text)
    await m.answer_document(document=FSInputFile(pdf_path))

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не указан в .env")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())