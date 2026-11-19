# Восстановление NURAY на другом компьютере

```sh
git clone https://github.com/NieMandX/NURAY.git
cd NURAY
python3 scripts/serve.py --port 8776
```

Маршруты `/moscow/`, `/spb/` и `/kursk/` загружают опубликованные сцены из Object Storage. Для редактирования скачайте рабочие исходники из закрытого бакета.

## Восстановление исходников

В авторизованной консоли Яндекс Облака откройте папку `nuray-workbench-20261120/` в бакете резервных копий. Файл `manifest.json` появляется после проверки всех частей. Скачайте его и все указанные в нём архивы в одну локальную папку. Если у вас настроен YC CLI с доступом к бакету, скачайте их одной командой:

```sh
mkdir -p .local/download-workbench
yc storage s3 cp "s3://${NURAY_BACKUP_BUCKET}/nuray-workbench-20261120/" .local/download-workbench/ --recursive
python3 scripts/restore_workbench.py .local/download-workbench
```

Задайте `NURAY_BACKUP_BUCKET` именем закрытого бакета в своём аккаунте. Команда восстановления проверяет размер и SHA-256 каждого архива и файла. Она использует пути относительно корня NURAY и остановится, если в месте восстановления уже лежит другая версия файла. Для проверки скачанного без распаковки добавьте `--verify-only`.

Рабочие пути внутри клона:

| Город | Исходный захват | Редактируемый выпуск |
| --- | --- | --- |
| Москва | `moscow-fidelity/source/2gis-moscow-20261021-10km-build` | `assets-moscow-10km-20261108-r1` |
| Петербург | `moscow-fidelity/source/2gis-spb-live-20261021-10km` | `assets-spb-10km-live-20261024-r13` |
| Курск | `moscow-fidelity/source/yandex-kursk-20261112-r1` и `kursk-2gis-20261112-r1` рядом с ним | `assets-kursk-3km-20261113-r14` |

Каталоги выпусков находятся под `moscow-fidelity/web-preview/prototype/tiles/`. Съёмка Курского Детинца и её извлечение восстанавливаются в `.local/kursk-survey/`, оригинал — `original/Detinets.dwg`. Указанные в старых квитанциях пути обрабатываются при их чтении. Для редактирования используйте исходники и канонические данные готовых выпусков. Для повторения экспериментов со старыми выпусками могут понадобиться их промежуточные сборки.

## Локальная копия для просмотра

```sh
python3 scripts/restore_assets.py --manifest docs/assets-moscow-10km-20261110-manifest.json --mode all
python3 scripts/restore_assets.py --manifest docs/assets-spb-20261113-manifest.json --mode all
python3 scripts/restore_assets.py --manifest docs/assets-kursk-20261113-r14-manifest.json --mode all
```

Для полного локального просмотра распакуйте `model.gltf.gz` и `model.bin.gz` Москвы из её папки `delivery-20261108-v1` в `merged/model.gltf` и `merged/model.bin`. У Петербурга и Курска распакуйте `delivery-20261113-v1/model.glb.gz` каждого выпуска в его `merged/model.glb`. Сверьте результат с `decodedSha256` в соответствующем `delivery.json`. Запустите `python3 scripts/serve.py --port 8776 --local-assets`.

## Сборочное окружение

```sh
python3.12 -m venv .local/venv
.local/venv/bin/python -m pip install -r moscow-fidelity/prototype/tiling/requirements-workbench.txt
sh scripts/build-region-python.sh scripts/build_moscow_expansion.py --help
```

Для упаковки тайлов нужен Node.js, для извлечения отдельных моделей — Blender. При необходимости укажите исполняемые файлы через `NURAY_PYTHON`, `NURAY_NODE` и `NURAY_BLENDER`. Сохранённые канонические данные позволяют продолжить редактирование от готовых выпусков. Перед новым прогоном для всех слоёв сверяйте выбранный этап, его входы и каталог результата с [HANDOFF](HANDOFF.md).
