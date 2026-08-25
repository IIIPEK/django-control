# Django Control — краткая справка

## Назначение

`django-control` — управляющий backend для FastAPI-сервисов. Он предоставляет
Django Admin для редактирования конфигурации и прав доступа, а также защищённый
read-only API, через который FastAPI получает разрешённые параметры, хеши
API-ключей, политики и опубликованный SQL-каталог.

Django и FastAPI могут работать на разных хостах, но используют Django как
единый control plane. Доступ администраторов разграничивается штатными
пользователями, группами и permissions Django.

## Управляемые данные

### Параметры FastAPI

- каталог определений параметров с типом, назначением, сервисом и признаком
  секретности;
- значения по окружениям, например `production`;
- приоритет значения из БД над значением каталога по умолчанию;
- `auto` и `auto-detect` для параметров выбора LLM-модели.

Секретные и инфраструктурные bootstrap-параметры остаются в серверном env-файле
и через configuration API не выдаются.

### API-ключи и политики

- ручное добавление либо автоматическая генерация ключа;
- хранение только SHA-256-хеша и короткого `key_id`;
- открытое значение сгенерированного ключа показывается один раз;
- срок действия и возможность отключения ключа;
- mail-политики: почтовые ящики, разрешения и домены получателей.

Почтовые permissions разделены по операциям: `mail.read` разрешает чтение,
`mail.mark_read` — явную установку статуса «прочитано» без выдачи
`mail.workflow`, а `mail.workflow` — операции обработки письма.

FastAPI получает хеши и проверяет предъявленные ему открытые ключи локально.

### Роли и scopes

Scopes назначаются ключу через переиспользуемые access roles. Основные роли:

- `mail-agent`;
- `sql-consumer`;
- `sql-maintainer`;
- `voice-client`;
- `diarization-client`.

Для SQL используются scopes:

- `sql.catalog.read` — чтение доступного каталога;
- `sql.query.execute` — выполнение опубликованных запросов;
- `sql.query.upload` — загрузка произвольного read-only SQL для доверенных
  операторов;
- `sql.query` — временный legacy scope периода миграции.

## SQL-каталог

SQL-доступ работает по принципу deny-by-default. Для выполнения запроса ключу
одновременно нужны:

1. роль с соответствующим SQL scope;
2. SQL access profile;
3. grant профиля на запрос;
4. активная публикация запроса в нужном окружении.

Каталог содержит:

- категории и понятные описания запросов;
- стабильные ключи `Q-00` и `Q-00-00`;
- неизменяемые SQL-ревизии с checksum;
- публикации ревизий по окружениям;
- параметры, лимиты и timeout;
- профили доступа и grants;
- составные `multi_step`-запросы с упорядоченными шагами.

Родитель `multi_step` не содержит SQL и самостоятельно не выполняется. Каждый
его шаг является отдельным опубликованным запросом со своей ревизией.

## Read-only API для FastAPI

Все маршруты требуют:

```http
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

Основные endpoints:

```text
GET /api/v1/config/<environment>/
GET /api/v1/credentials/<environment>/
GET /api/v1/credentials/mail/<environment>/
GET /api/v1/sql-catalog/<environment>/
```

Ответы поддерживают `ETag` и `If-None-Match`. SQL-текст выдаётся только
доверенному FastAPI control-plane клиенту и не возвращается обычным
пользователям SQL API.

## Команды импорта

Импорт каталога параметров из env-файла:

```powershell
python manage.py sync_fastapi_catalog `
  --env-file .\no_commit\fastapi-ai-backend.env `
  --environment production `
  --dry-run
```

Импорт SQL-реестра и файлов:

```powershell
python manage.py sync_sql_catalog `
  --registry-file C:\iv\Python\FastAPI_AI_backend\sql\registry.json `
  --environment production `
  --dry-run
```

После успешного preview команда повторяется без `--dry-run`. Импорт
идемпотентен: неизменившийся SQL использует прежнюю ревизию, изменившийся
создаёт новую. При импорте новая ревизия сразу назначается публикации указанного
окружения.

Удаление записи из `registry.json` само по себе не отключает существующую
публикацию в БД — её необходимо выключить через Django Admin.

## Развёртывание

- PostgreSQL используется как отдельная база control plane;
- runtime-секреты Django загружаются из `/etc/freen/django-control.env`;
- проект запускается Gunicorn от системного пользователя `django-control`;
- Nginx обслуживает static-файлы и проксирует Django;
- внешний Traefik публикует административный интерфейс по HTTPS;
- FastAPI хранит локальные защищённые кеши ответов control plane и ограничивает
  максимальный возраст данных.

## Проверка проекта

```powershell
python manage.py check
python manage.py test control --settings=config.test_settings
python manage.py makemigrations --check --dry-run
```
