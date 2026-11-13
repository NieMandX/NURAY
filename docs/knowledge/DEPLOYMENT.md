# Публикация и хранение

Код и интерфейс — [GitHub Pages](https://niemandx.github.io/NURAY/), репозиторий `NieMandX/NURAY`, ветка `main`, папка `moscow-fidelity/web-preview/`. Данные — **Yandex Object Storage**, `https://storage.yandexcloud.net/nuray-assets-niemandx/`. Обращений к Cloud.ru в текущей доставке нет.

## Выпуск от 10 ноября 2026

`assets-moscow-10km-20261108-r1` содержит Москву **10 × 10 км**. При открытии страницы загружается выбранный пользователем квадрат **3 × 3 км**, 169 готовых тайлов с небольшим запасом по краям. Остальные ячейки добавляются только нажатием в панели «Участки карты». Движение камеры не расширяет выбор. Повторное нажатие убирает добавленную ячейку; «Только начальный участок» сбрасывает выбор.

- Основная ссылка: https://niemandx.github.io/NURAY/
- Явный режим выбора: https://niemandx.github.io/NURAY/prototype/tiles/?layout=sectors&renderer=webgpu&engine=raster
- Полная карта по отдельному запросу: https://niemandx.github.io/NURAY/prototype/tiles/?layout=merged&renderer=webgpu&engine=raster
- Совместимый режим: `?layout=sectors&renderer=webgl2`. Его прежний лимит GPU сохраняется, поэтому он может показать только часть выбранной территории.

| Состав нового выпуска | Размер |
|---|---:|
| Все 600 облачных объектов | 8 541 751 700 байт |
| Контейнер 30 251 уникального файла мешей | 3 088 057 613 байт |
| Сжатые glTF + BIN полной карты | 3 780 539 398 байт |
| Геометрия начального квадрата, без общих текстур и метаданных | 428 942 880 байт |

30 850 логических файлов описаны в [manifest](../assets-moscow-10km-20261110-manifest.json). Контейнер читается HTTP Range; целиком его скачивать для начального сектора не требуется. `sectors-v1/index.json` и 100 небольших gzip-каталогов позволяют не читать полный каталог 315 МБ при старте. Секторные метаданные и pack не меняют геометрию или инстансы.

Полная сцена превышает предел формата GLB: используется glTF и один BIN, вместе 11 526 735 462 байта до сжатия. 33 логических объекта, 95 групп отрисовки, 362 328 инстансов. Полная WebGPU-растеризация проверена локально; рейтрейс всей 10-километровой сцены пока не помещается в текущие четыре GPU-буфера по 1 ГиБ. Просмотр выбранных тайлов сохраняет отдельный режим трассировки и его бюджет.

## Доступ и проверки

Публичный бакет содержит только runtime-ассеты. Приватные входы и ключи туда не загружаются. Прежний 5-километровый выпуск r14 и его ссылки сохранены. Лимит объёма публичного бакета — 20 ГиБ, класс `STANDARD`, CDN не подключён. CORS: GET/HEAD для GitHub Pages и ранее разрешённых localhost-портов 8765/8776; доступен Range. ACL и доступ к закрытому бакету не расширялись.

Все объекты нового выпуска проверены по размеру, SHA-256 в метаданных загрузки, MD5 каждой переданной части и контрольным диапазонам чтения. Дополнительная публичная проверка 600 объектов подтвердила размеры, CORS и Range: [протокол](../proof/moscow-10km-cloud-20261110.json). Сжатая доставка: [протокол](../proof/moscow-10km-delivery-20261110.json). Это проверка передачи и выборочных диапазонов, а не повторное полное скачивание всех 8,54 ГБ.

Файлы имеют `Cache-Control: public,max-age=31536000,immutable`. Не назначать `.gz` и `.pack` HTTP `Content-Encoding`: viewer распаковывает их самостоятельно. Новый выпуск нельзя перезаписывать; изменения данных публикуются под новым именем.

Публичный viewer проверен в Chrome: [протокол браузера](../proof/moscow-10km-browser-20261110.json), [совпадение кода Pages](../proof/moscow-10km-pages-20261110.json). Старт: 169 тайлов, 454,51 МиБ по счётчику viewer, 379 запросов вместо 4483 отдельных запросов в локальном варианте без pack. Добавление ячейки: 185 тайлов; сброс и отдаление камеры: 169 без новых запросов. 51 JavaScript- и 6 Python-проверок прошли в выпуске.

## Восстановление и публикация

```sh
python3 scripts/verify_cloud.py --manifest docs/assets-moscow-10km-20261110-manifest.json
python3 scripts/verify_delivery.py --require-cache
python3 scripts/restore_assets.py --manifest docs/assets-moscow-10km-20261110-manifest.json --mode all
```

Для обычного запуска на другом компьютере достаточно клонировать Git и выполнить `python3 scripts/serve.py --port 8776`: данные будут читаться из Яндекса. Для полностью автономной копии восстановить manifest, распаковать gzip glTF/BIN в `merged/model.gltf` и `merged/model.bin`; `scripts/serve.py --local-assets` использует локальные меши. Он потребует дополнительное место под распакованный BIN (11,53 ГБ). Проверка `--check-only` сверяет восстановленные файлы.

GitHub Actions перед публикацией проверяет viewer, целостность облачных объектов и gzip-доставку. Тяжёлые файлы не входят в Pages artifact или Git. `scripts/upload_cloud.py` поддерживает закрытый файл краткосрочного IAM-сеанса; постоянный новый ключ для этой публикации не создавался, файл токена не входит в Git.

Закрытый архив входов (2026-10-27, private location) относится к старому выпуску и в этой публикации не обновлялся. Не считать его архивом новой 10-километровой сборки. История миграции и старые контрольные суммы: [8 ноября](DEPLOYMENT-20261108.md), [7 ноября](DEPLOYMENT-20261107.md).


## Курск r12 — публикация 13 ноября 2026

Маршрут: https://niemandx.github.io/NURAY/kursk/ . Главный московский маршрут не меняется. WebGPU открывает объединённую сцену; WebGL2 использует готовые тайлы и полигональные растения.

Runtime: `assets-kursk-3km-20261113-r12`, сплаты: `assets-kursk-splats-20261113-r6`. Манифест: `docs/assets-kursk-20261113-manifest.json`. 73 объекта, 788 601 131 байт; 8 286 логических блоков упакованы в `meshes.pack` с Range-доступом. Исходный объединённый GLB — 891 319 732 байта, его gzip — 353 711 595 байт. Сжатие без потерь, полный обратный SHA проверен. Геометрия при публикации не перестраивалась.

Подготовка: `scripts/prepare_delivery.py`, затем `scripts/prepare_scene_release.py`. Все облачные объекты проверены загрузчиком по размеру/SHA-метаданным и трём диапазонам; публичная проверка CORS/Range — `docs/proof/kursk-cloud-20261113.json`, доставка — `kursk-delivery-20261113.json`. `.gz` и `.pack` выдаются без Content-Encoding, с immutable-кэшем. Вода Ocean, Hosek–Wilkie, 21 июня 2026 / 18:47, 64 сэмпла; вода заморожена. Все значения водного и светового пресета совпадают с утверждённым локальным просмотром.

Private workbench backup: 391,853,331 bytes; 536 verified files. Includes current canonical geometry, stage reports, decoded source, survey extraction and original PLYs. It is not every obsolete build or every original provider response. Uploaded to private Yandex storage after specific user approval. Size, checksum metadata and three byte ranges verified; anonymous HEAD returns 403 for archive and manifest. Exact location/checksum are in the private local receipt `.local/kursk-backup-location.json`; never publish that receipt. Public verification summary: `docs/proof/kursk-backup-20261113.json`. Restore the authorized workbench archive in the checkout root; restore public runtime with `restore_assets.py --manifest docs/assets-kursk-20261113-manifest.json --mode all`.

Основная публикация Pages прошла: commit `4d503f4`, workflow `43398346714`. Исправление совместимости WebGL: commit `d9e303b`, workflow `43399119087`, success. Окончательный код и ссылки скачивания: commit `6fc103c`, workflow `43399979070`, success; опубликованный app.js совпадает с локальным побайтно. Квитанция CI: `docs/proof/kursk-pages-ci-20261113.json`. Публичный WebGPU просмотр загрузил всю сцену и шесть шаблонов из Яндекс Cloud, без ошибок; переключение GS → полигоны → GS проверено. WebGL2 завершает загрузку и показывает полигональные растения; несовместимый параметр instanceCulling безопасно игнорируется. Проверены 67 JS-тестов, 7 доставки, 51 алгоритмов Курска, 4 Gaussian и 3 Float32 clipping. Нативный Safari в этой публикации не проверялся.

Для полностью автономного merged-просмотра после `restore_assets.py --mode all` дополнительно распаковать GLB (утилита восстановления проверяет и сохраняет gzip, но не распаковывает его автоматически):

```sh
python3 - <<'PY'
import gzip, shutil
from pathlib import Path
root = Path('moscow-fidelity/web-preview/prototype/tiles/assets-kursk-3km-20261113-r12')
target = root / 'merged/model.glb'
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    with gzip.open(root / 'delivery-20261113-v1/model.glb.gz', 'rb') as src, target.open('xb') as dst:
        shutil.copyfileobj(src, dst)
PY
```

После этого `python3 scripts/serve.py --port 8776 --local-assets` использует восстановленные локальные данные. Исходный DWG не включён в рабочий архив; сохранены его извлечение, привязка и данные для текущей сборки.

Браузерная проверка окончательной версии: `docs/proof/kursk-pages-20261113.json`. WebGPU загрузил полную карту со сплатами; WebGL2 — 1 подробный и 112 обзорных тайлов в существующем бюджете, с полигональными растениями. Ссылки GLB в обоих режимах ведут на опубликованный gzip. Краткосрочный локальный IAM-файл после передачи удалён.


## Курск r13 — исправленная труба, 13 ноября 2026

Маршрут `/kursk/` переключён на `assets-kursk-3km-20261113-r13` и сплаты `assets-kursk-splats-20261113-r7`. Прежний r12 сохранён для старых ссылок. Москва и Петербург не меняются. Труба плавно сужается и имеет восемь широких белых/красных полос; остальные поверхности и трансформации растений сохранены.

Манифест: `docs/assets-kursk-20261113-r13-manifest.json`. 73 облачных объекта, 788 609 504 байта. Полный GLB — 891 316 932 байта, gzip — 353 711 781 байт. 8 287 блоков тайлов упакованы в `meshes.pack` (282 689 955 байт). Все объекты загружены и проверены; публичные CORS/Range/размеры: `docs/proof/kursk-r13-cloud-20261113.json`. Gzip/immutable-кеш/контрольные диапазоны: `docs/proof/kursk-r13-delivery-20261113.json`. 61 JavaScript- и 7 Python-тестов передачи прошли перед публикацией. Ранее выполнены полные проверки геометрии и три теста построения трубы.

Восстановление: `python3 scripts/restore_assets.py --manifest docs/assets-kursk-20261113-r13-manifest.json --mode all`; для локального merged-просмотра распаковать `delivery-20261113-v1/model.glb.gz` в `merged/model.glb`, как в примере r12 выше. Частный workbench-архив r12 не обновлялся; алгоритм и инструкция применения r13 сохранены в Git.

Публикация r13 завершена: commit `f8b12af`, workflow `43416314113`, success. Публичный маршрут загрузил полную сцену и r7 сплаты без ошибок консоли, с прежними водой/светом и закрытыми панелями. Квитанция: `docs/proof/kursk-r13-pages-20261113.json`, изображение: `kursk-r13-published-20261113.png`.

- Kursk GS r8 (2026-11-13): new immutable prefix `assets-kursk-splats-20261113-r8/`, 21 objects / 33,127,958 bytes. `/kursk/` selects r8 with the existing r13 GLB. Workflow validates its new manifest before deployment. Old r7 and r13 objects retained; bucket access unchanged.
