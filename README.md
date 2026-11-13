# NURAY — городской макет и экспериментальный рендерер

Проект «Найти интересные идеи рендеринга»: алгоритмическая геометрия города из данных 2ГИС, собственные WebGPU/WebGL2 рендереры, PBR-растеризация и WebGPU-трассировка лучей.

**Актуальная кодовая база находится в `moscow-fidelity/`.** Старые корневые `src/` и прототипы сохранены для истории; GitHub Pages публикует `moscow-fidelity/web-preview/`.

- [Курск · радиус 3 км](https://niemandx.github.io/NURAY/kursk/)
- [Открыть viewer](https://niemandx.github.io/NURAY/)
- [База знаний и видение проекта](docs/knowledge/README.md)
- [Продолжить работу на другом компьютере](docs/knowledge/HANDOFF.md)
- [Архитектура и сборка](docs/knowledge/ARCHITECTURE.md)
- [Принятые визуальные решения](docs/knowledge/DECISIONS.md)
- [Размещение данных и публикация](docs/knowledge/DEPLOYMENT.md)
- [Московский пресет от 27 октября 2026](docs/moscow-approved-20261027.json)
- [Размеры и SHA-256 файлов сцены](docs/assets-moscow-10km-20261110-manifest.json)

Москва: **10 × 10 км**, выпуск `assets-moscow-10km-20261108-r1`. Сначала загружается выбранный квадрат **3 × 3 км**; соседние ячейки добавляются вручную в панели «Участки карты». По умолчанию — WebGPU-растеризация, физическое небо Hosek–Wilkie, Ocean и сохранённый свет. Настройки Петербурга не заменяются московскими.

Код, небольшие библиотечные ассеты и документация — здесь. Сшитый GLB, тайлы, текстуры сцены и ускорители трассировки — в Yandex Object Storage, бакет `nuray-assets-niemandx`. Секреты доступа в репозиторий не входят.

## Быстрый запуск

```sh
git clone https://github.com/NieMandX/NURAY.git
cd NURAY
python3 -m http.server 8776 --bind 127.0.0.1 --directory moscow-fidelity/web-preview
```

Открыть <http://127.0.0.1:8776/>. По умолчанию данные загружаются из Яндекс Cloud. Не открывайте `index.html` через `file://`: ES-модулям нужен HTTP.

Для локальной копии данных:

```sh
python3 scripts/restore_assets.py --manifest docs/assets-moscow-10km-20261110-manifest.json --mode all
```

Скрипт проверяет SHA-256 и восстанавливает тайлы из контейнера. Для автономного полного экспорта дополнительно распакуйте gzip glTF/BIN, как описано в [инструкции](docs/knowledge/DEPLOYMENT.md). Пересборка геометрии для просмотра готовой сцены не требуется.

![Начальный сектор Москвы на публичной странице](docs/proof/moscow-3km-public-20261110.png)
