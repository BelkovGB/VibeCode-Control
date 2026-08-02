<p align="center">
  <img src="assets/icon.svg" width="128" alt="VibeCode Control">
</p>

<h1 align="center">VibeCode Control</h1>

<p align="center">
  Управляющий контур для контролируемой AI-разработки с Codex, Claude, GitHub и CI.
</p>

<p align="center">
  <code>v0.1.0</code> · проекты на любом стеке · CLI: Python 3.10+ · 102 автотеста
</p>

<p align="center">
  <a href="#зачем-нужен-vibecode-control">Зачем</a> ·
  <a href="#что-он-делает">Возможности</a> ·
  <a href="#аудит-аналогов">Аудит аналогов</a> ·
  <a href="#быстрый-старт">Быстрый старт</a> ·
  <a href="#основные-сценарии">Сценарии</a> ·
  <a href="#справочник-команд">Команды</a> ·
  <a href="#безопасность">Безопасность</a>
</p>

---

VibeCode Control — это переиспользуемый скилл и локальный CLI, который подключает к отдельному репозиторию проверяемый процесс AI-разработки.

Он не пишет продукт «по волшебной кнопке». Он задаёт агентам роли, этапы, разрешения и обязательные доказательства, проверяет готовность проекта и требует не выдавать предположение модели за пройденный тест, зелёный CI или готовый релиз.

> Каждый продукт остаётся в собственном репозитории. VibeCode Control устанавливает в него локальный управляющий слой и не превращается в общий репозиторий со всем кодом.

## Зачем нужен VibeCode Control

AI-агенты умеют быстро писать код, но скорость сама по себе не гарантирует управляемую разработку. Без общего контура часто возникают одни и те же проблемы:

| Проблема | Что делает VibeCode Control |
|---|---|
| Агент начинает работу без понимания проекта | Инспектирует репозиторий, документы, Git, тесты, CI и риски до изменений |
| Новый и legacy-проект подключаются одинаково | Разделяет безопасные режимы `init` и `adopt`, сначала показывает dry-run |
| Непонятно, кто и на какой модели выполняет этап | Хранит исполняемый граф ролей, агентов, моделей, effort и разрешений и показывает режим и источник каждого параметра |
| Фоновый агент не видит нужные скиллы | Закрепляет версии, проверяет checksum и доставляет копии Codex и Claude |
| «Готово» подтверждено только текстом модели | Требует объективные проверки и evidence, привязанные к текущему Git SHA |
| Изменение конфигурации может повредить проект | Использует план, allowlist путей, SHA-256, атомарную запись и rollback |
| Процесс застрял или устарел | Диагностирует схему через `doctor` и переоценивает её через `scheme check` |

## Что он делает

- подключает новый или существующий репозиторий без массового переписывания файлов;
- ведёт настройку по этапам и всегда показывает один следующий практический шаг;
- хранит state graph разработки в `.agent-flow/workflow.json`;
- отделяет логические роли от конкретных агентов, моделей и permission profiles;
- хранит каждый `model` и `effort` с режимом `explicit`, `inherited`, `unset`, `not-applicable` или `undecided` и не подставляет значение вместо отсутствующего;
- поставляется нейтральным: шаблон не выбирает за проект исполнителя, модель, effort и язык отчётов, а setup останавливается, пока владелец не решит;
- собирает матрицу эффективной конфигурации с источником каждого значения, прикладывает её к плану и после применения перечитывает из файлов и сверяет ячейка в ячейку;
- требует по каждому узлу либо проверенный скилл, либо обоснованный `zero-skill`;
- предупреждает о review-узле без объявленных обязательных артефактов, запрещает ему `PASS` при записи запуска и принимает проверку только с conclusion `success`;
- закрепляет сторонние скиллы по commit SHA и контролирует их целостность;
- готовит проектные копии скиллов для `.agents/skills` и `.claude/skills`;
- проверяет Git, код, качество, CI, документацию, безопасность и skill dependencies;
- выполняет preflight отдельного фонового узла до запуска агента;
- записывает evidence конкретного запуска и связывает его с Issue, PR и head SHA;
- обнаруживает повреждённую или устаревшую схему и строит обратимый план исправления.

## Аудит аналогов

Перед публикацией VibeCode Control похожие решения на [skills.sh](https://skills.sh/) были проверены по содержимому их `SKILL.md`, а не только по названию, популярности или автоматическому бейджу.

**Итог: `KEEP`.** Полного аналога не найдено. Ближайшие кандидаты закрывают отдельные участки — планирование, TDD, review или оркестрацию выполнения, — но не весь контур от подключения репозитория и графа ролей до фоновых агентов, quality gates, merge gate, диагностики и управления зависимыми скиллами.

[Открыть полный датированный аудит skills.sh](docs/skills-sh-audit-2026-08-02.md) — с методикой, сравнением кандидатов, причинами отклонения, рекомендациями по узлам и ограничениями исследования.

> Аудит статический: одинаковые сравнительные запуски кандидатов на одном проекте пока не проводились, поэтому отчёт не заявляет эмпирическое превосходство.

## Как это устроено

```mermaid
flowchart TD
    A["VibeCode Control"] --> B["Управляющий слой проекта: .agent-flow"]
    B --> C["Узлы Codex"]
    B --> D["Узлы Claude"]
    B --> E["Гейты GitHub и CI"]
    C --> F["Доказательства для текущего Git SHA"]
    D --> F
    E --> F
```

В репозиторий проекта устанавливаются конфигурация, граф, CLI, шаблоны и project-scoped skills. GitHub, CI, тесты и branch protection остаются внешними механизмами принуждения: наличие одного `SKILL.md` или workflow-файла не считается доказательством, что удалённый гейт действительно настроен.

### Что VibeCode Control не делает

- не принимает вместо владельца продукта решения о scope, roadmap, бюджете или `GO / PIVOT / HOLD / STOP`;
- не подменяет GitHub rulesets, required checks, CI, тесты или review;
- не меняет production, платные настройки и удалённые права без отдельного полномочия;
- не обновляет сторонние скиллы из сети во время обычного фонового запуска;
- не утверждает, что модель «точно применила скилл»: проверяются доставка, явный вызов, целостность и результат.

## Требования для запуска VibeCode Control

> **Стек подключаемого проекта может быть любым:** Node.js, TypeScript, Java, Go, Flutter, Rust, Python или другой. VibeCode Control не требует переписывать проект на Python и не добавляет Python как зависимость приложения.

| Компонент | Требование |
|---|---|
| Проект | Любой язык, фреймворк и архитектура |
| CLI VibeCode Control | Python 3.10 или новее на машине, где запускается CLI |
| Работа с репозиторием | Git |
| Операционная система | Windows, Linux или macOS |
| Удалённые проверки и PR | Доступ к GitHub; для локальных проверок не требуется |

Python нужен только как среда выполнения служебного CLI. CLI использует стандартную библиотеку, поэтому устанавливать дополнительные Python-пакеты не требуется.

## Установка

### Вариант 1. Запуск из клона

Подходит, если нужно сначала попробовать инструмент без установки скилла.

Windows PowerShell:

```powershell
git clone https://github.com/BelkovGB/VibeCode-Control.git "$env:USERPROFILE\Tools\VibeCode-Control"
$VibeCodeControl = "$env:USERPROFILE\Tools\VibeCode-Control"
py "$VibeCodeControl\scripts\devflow.py" --repo "C:\projects\my-app" inspect
```

Linux/macOS:

```bash
git clone https://github.com/BelkovGB/VibeCode-Control.git "$HOME/tools/VibeCode-Control"
VIBECODE_CONTROL_DIR="$HOME/tools/VibeCode-Control"
python3 "$VIBECODE_CONTROL_DIR/scripts/devflow.py" --repo /path/to/my-app inspect
```

### Вариант 2. Установка как пользовательского скилла Codex

Codex загружает пользовательские скиллы из `$HOME/.agents/skills`. Клонируйте репозиторий в отдельную папку скилла `vibecode-control`:

Windows PowerShell:

```powershell
git clone https://github.com/BelkovGB/VibeCode-Control.git "$env:USERPROFILE\.agents\skills\vibecode-control"
```

Linux/macOS:

```bash
git clone https://github.com/BelkovGB/VibeCode-Control.git "$HOME/.agents/skills/vibecode-control"
```

После установки вызовите скилл явно:

```text
$vibecode-control Проверь этот репозиторий, покажи этапы настройки, граф и рекомендуемые скиллы по узлам.
```

Codex обнаруживает изменения скиллов автоматически. Если скилл не появился, перезапустите Codex. Подробнее: [официальная документация OpenAI о скиллах](https://learn.chatgpt.com/docs/build-skills).

### Вариант 3. Установка как пользовательского скилла Claude

Claude загружает пользовательские скиллы из `$HOME/.claude/skills`. Отличается только каталог, всё остальное симметрично Codex:

Windows PowerShell:

```powershell
git clone https://github.com/BelkovGB/VibeCode-Control.git "$env:USERPROFILE\.claude\skills\vibecode-control"
```

Linux/macOS:

```bash
git clone https://github.com/BelkovGB/VibeCode-Control.git "$HOME/.claude/skills/vibecode-control"
```

В Claude скилл вызывается по имени `vibecode-control` — например, «Используй скилл vibecode-control: проверь этот репозиторий, покажи этапы настройки, граф и рекомендуемые скиллы по узлам».

### Вариант 4. Установка командой `devflow install`

Поддерживаемый способ поставить и обновлять обе пользовательские копии из одного клона: в отличие от ручного `git clone` команда удаляет файлы прежней версии и проверяет результат. Сначала dry-run:

```bash
python3 <vibecode-control>/scripts/devflow.py install
```

Отчёт показывает источник, целевой каталог, число файлов, общий объём в байтах, контрольную сумму источника и установленной копии, а также списки создаваемых, обновляемых и удаляемых файлов. Затем запись:

```bash
python3 <vibecode-control>/scripts/devflow.py install --apply
python3 <vibecode-control>/scripts/devflow.py install --client claude --apply
python3 <vibecode-control>/scripts/devflow.py install --client codex --apply
```

- `--client codex|claude|both` — какой каталог обновлять, по умолчанию `both`;
- `--apply` — атомарная запись, удаление файлов прежней установки и повторный подсчёт контрольной суммы установленного дерева;
- `--force` — заменить чужой или посторонний каталог по этому пути; без флага команда отказывается его трогать.

Совпадение контрольных сумм доказывает, что установленная копия побайтово равна источнику и не содержит остатков прежней версии; расхождение даёт `BLOCKED`, а не молчаливую доустановку. Команда не пишет за пределы каталога скиллов выбранного клиента, отказывается работать с symlink-целью и не копирует `.git` (он же исключён из контрольной суммы).

> Логика процесса общая для Codex и Claude. Конфигурация исполнения — идентификаторы агентов, имена моделей, словари effort и permission profiles — специфична для клиента и не переносится между ними без отдельного решения. Перенос этапа с одного клиента на другой не переносит модель и effort исходного клиента.

## Быстрый старт

Сначала всегда выполняйте инспекцию только для чтения:

```bash
python3 <vibecode-control>/scripts/devflow.py --repo <project> inspect
```

CLI сообщит рекомендуемый режим:

- `init` — новый или фактически пустой репозиторий;
- `adopt` — действующий или legacy-проект.

### Новый проект

```bash
# 1. Показать план и diff без записи
python3 <vibecode-control>/scripts/devflow.py --repo <project> init

# 2. Применить тот же режим после проверки diff
python3 <vibecode-control>/scripts/devflow.py --repo <project> init --apply

# 3. Дальше использовать установленный project-local CLI
cd <project>
python3 .agent-flow/devflow.py setup next
```

### Существующий проект

```bash
# 1. Более глубокая инспекция
python3 <vibecode-control>/scripts/devflow.py --repo <project> inspect --deep

# 2. Показать безопасный план подключения
python3 <vibecode-control>/scripts/devflow.py --repo <project> adopt

# 3. Применить после проверки diff
python3 <vibecode-control>/scripts/devflow.py --repo <project> adopt --apply

# 4. Продолжить по этапам настройки
cd <project>
python3 .agent-flow/devflow.py setup next
```

В Windows замените `python3 .agent-flow/devflow.py` на `py .agent-flow\devflow.py`.

## Основные сценарии

### 1. Понять, чего не хватает проекту

```bash
python3 .agent-flow/devflow.py setup check
python3 .agent-flow/devflow.py setup next
```

Каждый этап возвращает один из четырёх статусов:

| Статус | Значение |
|---|---|
| `PASS` | Требование подтверждено фактическими доказательствами |
| `PARTIAL` | Работу можно продолжать осторожно, но остаётся пробел или внешняя проверка |
| `BLOCKED` | Продолжение нарушит обязательное решение, проверку целостности или safety gate |
| `NOT_APPLICABLE` | Этап обоснованно не нужен этому проекту |

### 2. Посмотреть реальный граф работы

```bash
python3 .agent-flow/devflow.py graph --format mermaid
python3 .agent-flow/devflow.py graph --format table
python3 .agent-flow/devflow.py config show --effective
```

Диаграмма всегда строится из `.agent-flow/workflow.json`, поэтому не расходится с исполняемой конфигурацией.

### 3. Настроить роли, модели и права

```bash
python3 .agent-flow/devflow.py role set implementer claude-code
python3 .agent-flow/devflow.py model set reviewer <model> --effort xhigh
python3 .agent-flow/devflow.py permissions set merge merge-verified-sha
python3 .agent-flow/devflow.py config effective --format table
```

> **Шаблон нейтрален.** Публичный project kit не выбирает за проект исполнителя, модель, effort и язык отчётов. Машинные роли поставляются как `agent: "unresolved"` с `model` и `effort` в `{"mode": "undecided"}`, `policy.language` — `"undecided"`. Конфигурация исполнения выбирается при настройке: `setup next` останавливается на этапе `context` до выбора языка и на этапе `roles` до выбора исполнителей, а `operate` и запись PASS запрещены, пока решение не принято. `undecided` — это «никто не выбирал», в отличие от `unset` — «владелец решил, что параметра нет».

Каждый `model` и `effort` в `.agent-flow/config.json` хранится с режимом:

| Режим | Значение |
|---|---|
| `{"mode": "explicit", "value": "<model или effort>"}` | Значение выбрано и закреплено |
| `{"mode": "inherited"}` | Значение определяет клиент во время запуска; его нужно наблюдать и записать, а не придумать |
| `{"mode": "unset"}` | Параметр намеренно отсутствует и никогда не материализуется в конкретное значение |
| `{"mode": "not-applicable"}` | Роль не исполняет модель: агент `human`, `script` или `deterministic` |
| `{"mode": "undecided"}` | Выбор ещё не сделан. Это состояние поставляет нейтральный шаблон; оно блокирует этап `roles`, preflight узла и запись PASS |

Голая строка — legacy-запись. Она принимается при чтении и нормализуется при записи (конкретное значение → `explicit`, `inherit` → `inherited`, `not-applicable` → `not-applicable`, `unset` → `unset`, `unconfigured` и `undecided` → `undecided`), но даёт предупреждение с точным указателем параметра. Пропущенный ключ `model` или `effort` — ошибка: режим `unset` пишется явно. Роль без исполняемой модели обязана использовать `not-applicable` для обоих параметров, а роль с исполняющим агентом не имеет права его использовать.

`config effective` строит матрицу `| Узел | Этап | Владелец | Agent | Model | Model mode | Model источник | Effort | Effort mode | Effort источник |`. Порядок разрешения для model и effort: `node_overrides[<узел>]` → `roles[<роль узла>]` → отсутствует; для permissions: `node_overrides[<узел>]` → узел в `workflow.json` → `roles[<роль узла>]`. Источник называет уровень (`node-override`, `role`, `node`, `absent`), указатель вида `roles.reviewer.model` и файл. Ключи `model` и `effort` на уровне узла в `workflow.json` — ошибка валидации, а не молча игнорируемое поле.

Матрица прикладывается только к плану, который переписывает `.agent-flow/config.json` или `.agent-flow/workflow.json`. Так более ранний запуск остаётся проверяемым после позднейшего разрешённого изменения конфигурации. После применения она перестраивается из фактических файлов на диске и сверяется с утверждённым планом ячейка в ячейку: расхождение прерывает apply с откатом записи, а `devflow verify` возвращает `BLOCKED` со списком `effective_configuration_drift`. Fallback и автоматического согласования нет.

Изменения применяются к будущим запускам. Если доступность модели или effort не проверена на реальной платформе, статус останется `PARTIAL` или `BLOCKED`. Управляемый блок инструкций Claude не фиксированный шаблон: он генерируется из установленной конфигурации и перечисляет только роли, чей агент отображается на Claude, их permission profiles и принадлежащие им узлы. Право на merge он даёт лишь тогда, когда назначена роль `release-operator`; если Claude не назначена ни одна роль, блок так и написан и не объявляет Claude исполнителем. Блоки перегенерируются в `init`, `adopt`, `upgrade` и `repair`, а `role set` allowlist записи не расширяет: после переназначения роли выполните `devflow upgrade`, иначе `devflow doctor` вернёт `PARTIAL` по проверке `managed-blocks`.

#### Миграция уже установленного проекта

Проект, настроенный до типизированного контракта, переводится отдельной командой:

```bash
python3 .agent-flow/devflow.py config normalize
python3 .agent-flow/devflow.py config normalize --apply
```

Без `--apply` команда показывает план и diff. Она переписывает нетипизированные `model` и `effort` в каноническую типизированную форму, детерминирована и идемпотентна: повторный запуск возвращает `NOT_APPLICABLE`. Если результат оказался бы невалидным, команда возвращает `BLOCKED` и ничего не пишет. `schema_version` остаётся `1`.

Граф, написанный до контракта артефактов review, дополняется командой `graph --migrate`:

```bash
python3 .agent-flow/devflow.py graph --migrate
python3 .agent-flow/devflow.py graph --migrate --apply
```

Команда добавляет недостающие контракты только тем id узлов, которые есть и в каноническом поставляемом графе, только копированием его объявления и только когда каждый ключ контракта уже присутствует в `expected_evidence` этого узла. Review-узлу, которого нет в поставке, вид артефакта не угадывается: такой узел перечисляется в `requires_explicit_decision`, и оператор добавляет `evidence_contract` в `.agent-flow/workflow.json` явно. Dry-run возвращает `PARTIAL` с планом и diff; `--apply` пишет через обычную машинерию планов в новом режиме `graph-migrate`, которому разрешено записывать `.agent-flow/workflow.json` и ничего больше. Граф, где контракты уже объявлены, возвращает `NOT_APPLICABLE`.

Полный порядок миграции проекта, установленного до этого изменения:

```bash
python3 .agent-flow/devflow.py config normalize --apply   # типизированные model и effort
python3 .agent-flow/devflow.py graph --migrate --apply    # контракты артефактов review
python3 .agent-flow/devflow.py upgrade --apply            # управляемые инструкции и project CLI
```

### 4. Выбрать скиллы для узлов

```bash
python3 .agent-flow/devflow.py skills recommend
python3 .agent-flow/devflow.py skills explain implement
python3 .agent-flow/devflow.py skills none --node quality_gates --reason "CI закрывает задачу"
python3 .agent-flow/devflow.py skills verify --node implement
```

`zero-skill` — нормальное решение, если задачу надёжнее закрывают модель, правила проекта, детерминированный скрипт, CI или другой объективный гейт.

### 5. Проверить узел перед фоновым запуском

```bash
python3 .agent-flow/devflow.py operate --node implement
```

Preflight проверяет граф, профиль исполнителя, разрешения, skill decisions, целостность локальных копий и доступность обязательных внешних условий. Ответ также содержит `effective_configuration` — строку матрицы для этого узла с режимами и источниками, `required_artifacts` — обязательные артефакты узла, и `self_modification` — базовую ссылку, merge base и список защищённых путей, которые меняет текущая ветка (`.agent-flow/`, `AGENTS.md`, `CLAUDE.md`, `.github/workflows/`, `.github/devflow/prompts/`, обе копии скилла `devflow-node`). Если базу нельзя определить локально, preflight говорит об этом прямо и не угадывает.

### 6. Найти причину сбоя

```bash
# Быстрая офлайн-диагностика
python3 .agent-flow/devflow.py doctor

# Глубокая проверка всех слоёв
python3 .agent-flow/devflow.py audit all --deep

# Переоценка графа, ролей, моделей, гейтов и скиллов
python3 .agent-flow/devflow.py scheme check
```

`doctor` подходит для регулярной проверки; его проверка `managed-blocks` даёт `BLOCKED` при отсутствующем блоке или задвоенных маркерах и `PARTIAL`, если блок устарел относительно назначенных ролей. `scheme check` нужен при повторных сбоях, смене модели, стека или архитектуры, обновлении VibeCode Control или наступлении даты пересмотра скилла.

### 7. Проверить или откатить применённый план

```bash
python3 .agent-flow/devflow.py verify <run-id> --expected-manifest-sha256 <manifest-sha256>
python3 .agent-flow/devflow.py rollback <run-id> --expected-manifest-sha256 <manifest-sha256>
```

Rollback остановится, если после применения управляемый файл был изменён вручную или другим агентом. Новая работа не затирается.

## Справочник команд

Ниже `devflow …` — короткая запись аргументов после префикса:

```text
python3 <path-to-devflow.py> --repo <project>
```

После `init` или `adopt` используйте project-local префикс `python3 .agent-flow/devflow.py`. Команда `devflow help` печатает точный префикс для текущего репозитория.

<details>
<summary><strong>Справка, инспекция и аудит</strong></summary>

```text
devflow --version
devflow help [overview|modes|setup|configuration|install|skills|safety|windows]
devflow inspect [--deep] [--output .agent-flow/.local/reports/<new-name>.json]
devflow audit git|code|quality|ci|docs|security|skills|all [--deep]
devflow doctor [--deep] [--refresh-skills] [--repair-plan]
devflow scheme check [--no-refresh-skills]
```

</details>

<details>
<summary><strong>Установка, обновление, планы и rollback</strong></summary>

```text
devflow install [--client codex|claude|both] [--apply] [--force] [--home <path>]
devflow init|adopt|upgrade [--apply] [--full-diff] [--diff-path <relative-path>]
devflow plan init|adopt|upgrade|repair [--output .agent-flow/.local/plans/<new-name>.json] [--full-diff] [--diff-path <relative-path>]
devflow apply --plan <relative-path> --expected-sha256 <reviewed-plan-sha256>
devflow verify <run-id> --expected-manifest-sha256 <manifest-sha256>
devflow rollback <run-id> --expected-manifest-sha256 <manifest-sha256>
devflow scheme repair [--apply]
```

Без `--apply` изменяющие режимы показывают план. Сохранённый план применяется только с SHA-256, который был выведен при сохранении именно этой версии плана. `devflow install` относится к пользовательским копиям скилла, а не к репозиторию проекта: он пишет только в `~/.agents/skills/vibecode-control` или `~/.claude/skills/vibecode-control`.

</details>

<details>
<summary><strong>Этапы настройки и статус</strong></summary>

```text
devflow setup check [--stage <id>]
devflow setup next
devflow setup mark <stage> <PASS|PARTIAL|BLOCKED|NOT_APPLICABLE> --evidence <reference> [--note <text>]
devflow status
devflow next
```

`setup mark` предназначен только для доказательств, которые нельзя получить локально. Ручной `PASS` не перекрывает детерминированную ошибку схемы, checksum или безопасности.

</details>

<details>
<summary><strong>Граф, конфигурация, роли и модели</strong></summary>

```text
devflow graph --format mermaid|table|json
devflow graph --migrate [--apply] [--full-diff]
devflow config show [--effective]
devflow config effective [--format table|json]
devflow config normalize [--apply] [--full-diff]
devflow config set <dotted-path> <JSON-or-string>
devflow role set <role> <agent>
devflow model set <role-or-node> <model> [--effort <level>]
devflow permissions set <role-or-node> <profile>
```

`config effective` печатает матрицу узлов с режимом и источником каждого `model` и `effort`. `config normalize` переводит установленный проект на типизированную запись этих параметров: без `--apply` — план и diff, повторный запуск — `NOT_APPLICABLE`. `graph --migrate` добавляет графу, написанному до контракта артефактов review, недостающие `evidence_contract` — только по узлам канонического поставляемого графа; остальные review-узлы попадают в `requires_explicit_decision` и требуют явного решения оператора. В `model set` значение принимается и как конкретная модель, и как `inherit`, `unset` или `not-applicable`; после переназначения роли выполните `devflow upgrade`, чтобы обновить управляемые блоки инструкций.

</details>

<details>
<summary><strong>Управление зависимыми скиллами</strong></summary>

```text
devflow skills list
devflow skills recommend|plan [--node <id>]
devflow skills explain <node>
devflow skills search [--node <id>]
devflow skills register|update <name> --path <folder> --source <url> --commit <40-char-sha> --license <license> [--targets claude,codex] --approved-by-user [--apply]
devflow skills assign <name> --node <id> [--level required|recommended|optional] [--reason <text>]
devflow skills none --node <id> --reason <text>
devflow skills unassign <name> --node <id>
devflow skills remove <name> [--apply]
devflow skills audit [--node <id>] [--deep]
devflow skills verify [--node <id>]
devflow skills sync [--apply]
devflow skills evaluate <node>
```

Регистрация требует предварительного аудита точного содержимого, полного commit SHA и явного подтверждения пользователя. Обычный run ничего не скачивает из сети.

</details>

<details>
<summary><strong>Фоновые узлы и evidence</strong></summary>

```text
devflow operate --node <id>
devflow run record --node <id> --status <status> --head-sha <sha> --issue <ref> --pr <ref> --evidence "<expected-evidence>=<artifact-ref>" [--check NAME=CONCLUSION] [--actual-agent <id>] [--actual-model <id>] [--actual-effort <level>]
devflow run show [run-id]
```

Для успешной записи delivery-узла нужны фактический Git HEAD, чистое рабочее дерево, Issue/PR, пройденный preflight, реальный профиль исполнителя и отдельная ссылка на артефакт для каждого ожидаемого evidence.

Узел может объявить `evidence_contract`: имя из `expected_evidence` → `{"kind": "review"|"comment"|"findings"|"report"|"check-run", "required": true}`. В поставляемом графе он объявлен у `implementer_review` («отчёт самопроверки» → `findings`) и у `final_review` («вердикт review, привязанный к head SHA» → `review`). Review-узел без обязательного артефакта даёт предупреждение валидации: оно называет узел и говорит, что `PASS` для него запрещён, пока граф не мигрирован. Граф при этом остаётся валидным, поэтому `doctor`, `upgrade` и сама миграция продолжают работать. Гейт стоит там, где он и нужен: `devflow run record` отказывает в `PASS` на review-узле без объявленного обязательного артефакта и называет в ошибке команду миграции. Правила формы остаются жёсткими ошибками валидации: ключ контракта, которого нет в `expected_evidence`, неизвестный вид артефакта и небулево `required`. Каждый артефакт по контракту записывается как `<name>=<kind>:<reference>`.

`--check NAME=CONCLUSION` записывает наблюдаемый результат проверки. Допустимые conclusion: `success`, `failure`, `cancelled`, `skipped`, `neutral`, `timed_out`, `action_required`, `stale`. Проверку доказывает только `success`: любой другой записанный conclusion, включая зелёный `skipped`, блокирует `PASS`, а каждая проверка из `config.github.required_checks` должна быть отчитана с `success`. Гейт применяется на стадиях `verification`, `review` и `release`. На стадиях `implementation` conclusions записываются как доказательство и не гейтятся: узел `tdd_red` обязан доказать легитимно падающий тест, поэтому `--check tests=failure` там фиксируется и не блокирует PASS. После merge не диспатчьте workflow против закрытого PR, если ему нужен `refs/pull/<N>/merge`: на post-merge-узле (id `post_merge` или состояние `POST_MERGE_VERIFY`) CLI отклоняет evidence с такой ссылкой, потому что у закрытого PR её нет и запуск по ней фабрикует результат. До merge этот ref — канонический ориентир merge-гейта и остаётся рабочим.

Запись запуска хранит `checks`, а также `configured.modes` и `configured.sources` по каждому параметру. Сверка настроенного с фактическим учитывает режим: `explicit` обязан совпасть точно; `inherited` требует фактически наблюдённое значение; `unset` требует наблюдённое значение и остаётся `unset` в конфигурации; `not-applicable` отвергает любое фактическое значение как выдуманное.

</details>

Подробные пояснения и примеры: [references/setup-and-commands.md](references/setup-and-commands.md).

## Этапы первоначальной настройки

VibeCode Control ведёт репозиторий через десять независимых setup-этапов:

1. инспекция;
2. контекст продукта;
3. роли, агенты, модели, effort и permissions;
4. state graph;
5. каноническая документация;
6. локальный Git и удалённый GitHub;
7. baseline и quality gates;
8. решение по скиллам каждого узла;
9. фоновая автоматизация;
10. один низкорисковый пилотный Issue.

Этапы настройки не равны этапам продукта. Подсказка `setup next` не утверждает продуктовый scope и не заменяет решение PM.

## Безопасность

VibeCode Control спроектирован по принципу fail-closed:

- read-only команды не изменяют репозиторий;
- изменяющие команды сначала показывают план и diff;
- запись разрешена только внутри репозитория и по allowlist путей;
- symlink traversal, path traversal, force push и опасные операции блокируются;
- запись выполняется атомарно, а apply оставляет проверяемый rollback manifest;
- значения предполагаемых секретов не выводятся в отчёты;
- аудит стороннего скилла не исполняет его скрипты;
- evidence и готовность привязываются к текущему head SHA;
- непроверенные GitHub rulesets, required checks, модели и runners не получают ложный `PASS`.

Это защитный слой процесса, а не замена sandbox, branch protection, code review, CI или security tooling.

## Структура репозитория

| Путь | Назначение |
|---|---|
| [`SKILL.md`](SKILL.md) | Главная инструкция скилла и правила его срабатывания |
| [`scripts/devflow.py`](scripts/devflow.py) | Самодостаточный CLI управляющего контура |
| [`scripts/test_devflow.py`](scripts/test_devflow.py) | Unit- и regression-тесты CLI |
| [`assets/project-kit`](assets/project-kit) | Схемы, конфигурация, workflow и управляемые шаблоны для проекта |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Фактические компоненты, потоки данных, источники истины и trust boundaries |
| [`references`](references) | Подробные правила настройки, графа, качества, безопасности и skill governance |
| [`agents/openai.yaml`](agents/openai.yaml) | Метаданные скилла для OpenAI-совместимых поверхностей |
| [`docs/skills-sh-audit-2026-08-02.md`](docs/skills-sh-audit-2026-08-02.md) | Датированный аудит похожих решений на skills.sh |

## Разработка и проверка

Проверить CLI перед PR:

```bash
python3 -m py_compile scripts/devflow.py scripts/test_devflow.py
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/devflow.py --version
```

Текущий набор содержит 102 автоматических теста: установка и обновление, граф, rollback, checksum drift, повреждённая конфигурация, опасные сторонние скиллы, delivery evidence, remote-gate preflight, типизированные model и effort, матрица эффективной конфигурации, миграция `config normalize` и `graph --migrate`, гейт review-артефактов, нейтральность публичного шаблона и установка пользовательского скилла.

В Windows задайте `PYTHONUTF8=1` перед запуском тестов (`$env:PYTHONUTF8 = "1"`). Два теста проверяют symlink и требуют режима разработчика или прав администратора.

## Дополнительные материалы

- [Полная справка и этапы настройки](references/setup-and-commands.md)
- [Архитектура и границы ответственности](docs/ARCHITECTURE.md)
- [Конфигурация и state graph](references/configuration-and-graph.md)
- [Процесс разработки и quality gates](references/process-and-quality.md)
- [Skill Dependency Manager](references/skill-governance.md)
- [GitHub, фоновые агенты и безопасность](references/adapters-and-security.md)
- [Аудит похожих скиллов на skills.sh](docs/skills-sh-audit-2026-08-02.md)

## Совместимость имён

Публичное имя скилла — `vibecode-control`. Внутренние идентификаторы `devflow`, `.agent-flow` и `devflow-node` сохранены для совместимости существующего CLI, project kit и установленных проектов.
