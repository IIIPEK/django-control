from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class CategorySpec:
    code: str
    name: str
    description: str
    sort_order: int


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    category: str
    service: str
    label: str
    description: str
    data_type: str = 'string'
    default_value: Any = None
    validation_rules: dict[str, Any] = field(default_factory=dict)
    source: str = 'database'
    is_secret: bool = False
    is_required: bool = False
    requires_restart: bool = True
    sort_order: int = 0


CATEGORIES = (
    CategorySpec('runtime', 'Runtime', 'Общие параметры запуска и обработки запросов.', 10),
    CategorySpec('logging', 'Logging', 'Формат и уровень журналирования.', 20),
    CategorySpec('llm', 'LLM and classification', 'VLM/LLM endpoints, модели и классификация.', 30),
    CategorySpec('ocr', 'OCR', 'Параметры OCR и извлечения текста.', 40),
    CategorySpec('sqlanywhere', 'SQL Anywhere', 'Подключение к учётной SQL Anywhere.', 50),
    CategorySpec('postgresql', 'PostgreSQL', 'Bootstrap-подключение FastAPI к PostgreSQL.', 60),
    CategorySpec('sql-api', 'SQL query API', 'Каталог, выполнение и ограничения SQL API.', 70),
    CategorySpec('voice', 'Voice and diarization', 'Whisper, diarization и обработка аудио.', 80),
    CategorySpec('mail', 'Microsoft Graph mail', 'Почтовый gateway, вложения и worker.', 90),
    CategorySpec('digidoc', 'DigiDoc and SiVa', 'Проверка и распаковка DigiDoc-контейнеров.', 100),
    CategorySpec('security', 'Credentials and access', 'Секреты, остающиеся во внешнем окружении.', 110),
)


def _spec(
    key: str,
    category: str,
    service: str,
    label: str,
    description: str,
    *,
    data_type: str = 'string',
    default: Any = None,
    rules: dict[str, Any] | None = None,
    source: str = 'database',
    secret: bool = False,
    required: bool = False,
    restart: bool = True,
    order: int = 0,
) -> ParameterSpec:
    return ParameterSpec(
        key=key,
        category=category,
        service=service,
        label=label,
        description=description,
        data_type=data_type,
        default_value=default,
        validation_rules=rules or {},
        source=source,
        is_secret=secret,
        is_required=required,
        requires_restart=restart,
        sort_order=order,
    )


PARAMETERS = (
    _spec('APP_ENV', 'runtime', 'fastapi', 'Application environment', 'Имя текущего окружения FastAPI.', default='dev', rules={'choices': ['dev', 'development', 'staging', 'production']}, source='env', required=True, order=10),
    _spec('MIN_TEXT_CHARS', 'runtime', 'fastapi', 'Minimum text length', 'Минимальное число символов для принятия извлечённого текста.', data_type='integer', default=100, rules={'min': 1}, order=20),
    _spec('REQUEST_TIMEOUT', 'runtime', 'fastapi', 'Request timeout', 'Общий таймаут внешнего запроса в секундах.', data_type='float', default=600, rules={'min': 1, 'max': 3600}, order=30),
    _spec('LOG_LEVEL', 'logging', 'fastapi', 'Log level', 'Уровень журналирования приложения.', default='INFO', rules={'choices': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']}, order=10),
    _spec('LOG_FORMAT', 'logging', 'fastapi', 'Log format', 'Формат журналов: текст или JSON.', default='text', rules={'choices': ['text', 'json']}, order=20),

    _spec('LLAMA_URL', 'llm', 'fastapi', 'VLM chat endpoint', 'OpenAI-compatible endpoint основной VLM.', data_type='url', default='http://127.0.0.1:8080/v1/chat/completions', required=True, order=10),
    _spec('VLM_MODEL', 'llm', 'fastapi', 'VLM model', 'Явное имя VLM; при отсутствии определяется через /v1/models.', order=20),
    _spec('CLASSIFICATION_LLM_URL', 'llm', 'fastapi', 'Classification LLM endpoint', 'OpenAI-compatible endpoint модели классификации.', data_type='url', order=30),
    _spec('CLASSIFICATION_LLM_MODEL', 'llm', 'fastapi', 'Classification model', 'Имя модели для классификации документов.', order=40),
    _spec('CLASSIFICATION_LLM_TIMEOUT_SECONDS', 'llm', 'fastapi', 'Classification timeout', 'Таймаут запроса классификации в секундах.', data_type='float', default=120, rules={'min': 1, 'max': 3600}, order=50),

    _spec('OCR_PROMPT', 'ocr', 'fastapi', 'OCR prompt', 'Инструкция модели для дословного извлечения текста из изображения.', default='Extract all visible text from the image. Do not translate. Do not summarize. Do not explain. Preserve original language, line breaks, numbers, punctuation, tables and currency symbols. Return only the extracted text.', rules={'min_length': 10}, order=10),

    _spec('SQLANY_SERVERNAME', 'sqlanywhere', 'sql-query', 'SQL Anywhere server name', 'Имя сервера SQL Anywhere.', required=True, order=10),
    _spec('SQLANY_DBN', 'sqlanywhere', 'sql-query', 'SQL Anywhere database', 'Имя базы данных SQL Anywhere.', required=True, order=20),
    _spec('SQLANY_ASTART', 'sqlanywhere', 'sql-query', 'SQL Anywhere autostart', 'Разрешение автоматического запуска базы драйвером.', default='No', rules={'choices': ['Yes', 'No']}, order=30),
    _spec('SQLANY_HOST', 'sqlanywhere', 'sql-query', 'SQL Anywhere host', 'Адрес и порт SQL Anywhere.', required=True, order=40),
    _spec('SQLANY_UID', 'security', 'sql-query', 'SQL Anywhere user', 'Имя пользователя SQL Anywhere; хранится только в окружении.', source='env', secret=True, required=True, order=10),
    _spec('SQLANY_PWD', 'security', 'sql-query', 'SQL Anywhere password', 'Пароль SQL Anywhere; хранится только в окружении.', source='env', secret=True, required=True, order=20),

    _spec('PG_HOST', 'postgresql', 'fastapi', 'PostgreSQL host', 'Bootstrap-адрес PostgreSQL; необходим до чтения управляемой конфигурации.', source='env', required=True, order=10),
    _spec('PG_PORT', 'postgresql', 'fastapi', 'PostgreSQL port', 'Bootstrap-порт PostgreSQL.', data_type='integer', default=5432, rules={'min': 1, 'max': 65535}, source='env', required=True, order=20),
    _spec('PG_DATABASE', 'postgresql', 'fastapi', 'PostgreSQL database', 'Bootstrap-имя рабочей базы FastAPI.', source='env', required=True, order=30),
    _spec('PG_SCHEMA', 'postgresql', 'fastapi', 'PostgreSQL schema', 'Рабочая схема FastAPI.', default='public', rules={'regex': '^[A-Za-z_][A-Za-z0-9_]*$'}, source='env', required=True, order=40),
    _spec('PG_USER', 'postgresql', 'fastapi', 'PostgreSQL user', 'Bootstrap-пользователь PostgreSQL.', source='env', required=True, order=50),
    _spec('PG_PASSWORD', 'security', 'fastapi', 'PostgreSQL password', 'Пароль PostgreSQL; хранится только в окружении.', source='env', secret=True, required=True, order=30),

    _spec('SQL_DIR', 'sql-api', 'sql-query', 'SQL directory', 'Каталог SQL-файлов.', default='/opt/fastapi-backend/sql', rules={'min_length': 1}, order=10),
    _spec('SQL_REGISTRY_FILE', 'sql-api', 'sql-query', 'SQL registry file', 'Путь к registry.json каталога SQL-запросов.', default='/opt/fastapi-backend/sql/registry.json', rules={'min_length': 1}, order=20),
    _spec('SQL_QUERY_TIMEOUT_SECONDS', 'sql-api', 'sql-query', 'SQL query timeout', 'Максимальное время выполнения SQL API в секундах.', data_type='float', default=120, rules={'min': 1, 'max': 3600}, order=30),
    _spec('SQL_QUERY_MAX_RESPONSE_BYTES', 'sql-api', 'sql-query', 'Maximum SQL response', 'Максимальный размер ответа SQL API в байтах.', data_type='integer', default=10485760, rules={'min': 1024}, order=40),
    _spec('SQL_UPLOAD_MAX_BYTES', 'sql-api', 'sql-query', 'Maximum SQL upload', 'Максимальный размер загружаемого SQL-файла в байтах.', data_type='integer', default=1048576, rules={'min': 1024}, order=50),
    _spec('SQL_QUERY_API_KEY', 'security', 'sql-query', 'SQL query API key', 'Ключ доступа SQL API; хранится только в окружении.', source='env', secret=True, required=True, order=40),

    _spec('WHISPER_MODEL_PATH', 'voice', 'voice', 'Whisper model path', 'Локальный путь к модели faster-whisper.', default='/opt/models/faster-whisper-medium', rules={'min_length': 1}, order=10),
    _spec('WHISPER_MODEL_NAME', 'voice', 'voice', 'Whisper model name', 'Имя модели Whisper для журналов и метаданных.', default='medium', rules={'min_length': 1}, order=20),
    _spec('WHISPER_DEVICE', 'voice', 'voice', 'Whisper device', 'Устройство выполнения Whisper.', default='cuda', rules={'choices': ['cpu', 'cuda']}, order=30),
    _spec('WHISPER_DEVICE_INDEX', 'voice', 'voice', 'Whisper device index', 'Индекс GPU/устройства Whisper.', data_type='integer', default=0, rules={'min': 0}, order=40),
    _spec('WHISPER_COMPUTE_TYPE', 'voice', 'voice', 'Whisper compute type', 'Тип вычислений faster-whisper.', default='int8_float16', rules={'min_length': 1}, order=50),
    _spec('WHISPER_MAX_FILE_BYTES', 'voice', 'voice', 'Maximum audio file', 'Максимальный размер аудиофайла в байтах.', data_type='integer', default=262144000, rules={'min': 1024}, order=60),
    _spec('WHISPER_MAX_DURATION_SECONDS', 'voice', 'voice', 'Maximum audio duration', 'Максимальная длительность аудио в секундах.', data_type='float', default=3600, rules={'min': 1}, order=70),
    _spec('WHISPER_BEAM_SIZE', 'voice', 'voice', 'Whisper beam size', 'Размер beam search Whisper.', data_type='integer', default=5, rules={'min': 1, 'max': 100}, order=80),
    _spec('WHISPER_DIARIZATION_ENABLED', 'voice', 'voice', 'Enable diarization', 'Включение определения говорящих.', data_type='boolean', default=False, order=90),
    _spec('DIARIZATION_BACKEND', 'voice', 'voice', 'Diarization backend', 'Локальный или удалённый backend diarization.', default='local', rules={'choices': ['local', 'remote']}, order=100),
    _spec('DIARIZATION_URL', 'voice', 'voice', 'Diarization endpoint', 'HTTP endpoint удалённого diarization.', data_type='url', default='http://127.0.0.1:8020/diarize', order=110),
    _spec('DIARIZATION_TIMEOUT', 'voice', 'voice', 'Diarization timeout', 'Таймаут diarization в секундах.', data_type='float', default=900, rules={'min': 1, 'max': 7200}, order=120),
    _spec('DIARIZATION_MODEL_PATH', 'voice', 'voice', 'Diarization model path', 'Локальный путь к модели pyannote.', default='/opt/models/pyannote-speaker-diarization-3.1', order=130),
    _spec('DIARIZATION_DEVICE', 'voice', 'voice', 'Diarization device', 'Устройство выполнения локального diarization.', default='cuda', rules={'choices': ['cpu', 'cuda']}, order=140),
    _spec('DIARIZATION_DEVICE_INDEX', 'voice', 'voice', 'Diarization device index', 'Индекс устройства diarization.', data_type='integer', default=0, rules={'min': 0}, order=150),
    _spec('VOICE_API_KEY', 'security', 'voice', 'Voice API key', 'Ключ доступа voice API; хранится только в окружении.', source='env', secret=True, required=True, order=50),
    _spec('DIARIZATION_API_KEY', 'security', 'voice', 'Diarization API key', 'Ключ удалённого diarization; хранится только в окружении.', source='env', secret=True, order=60),
    _spec('HUGGINGFACE_TOKEN', 'security', 'voice', 'Hugging Face token', 'Токен загрузки моделей; хранится только в окружении.', source='env', secret=True, order=70),

    _spec('MAIL_GRAPH_TENANT_ID', 'mail', 'mail-graph', 'Azure tenant ID', 'Tenant ID приложения Microsoft Graph.', required=True, order=10),
    _spec('MAIL_GRAPH_CLIENT_ID', 'mail', 'mail-graph', 'Azure client ID', 'Client ID приложения Microsoft Graph.', required=True, order=20),
    _spec('MAIL_GRAPH_DEFAULT_MAILBOX', 'mail', 'mail-graph', 'Default mailbox', 'Почтовый ящик по умолчанию.', default='active_bot@freen.com', order=30),
    _spec('MAIL_GRAPH_ALLOWED_MAILBOXES', 'mail', 'mail-graph', 'Allowed mailboxes', 'Разделённый запятыми список разрешённых mailbox.', order=40),
    _spec('MAIL_GRAPH_TEMP_DIR', 'mail', 'mail-graph', 'Mail temporary directory', 'Каталог временных почтовых вложений.', default='/var/tmp/fastapi-mail-graph', order=50),
    _spec('MAIL_GRAPH_MAX_ATTACHMENT_MB', 'mail', 'mail-graph', 'Maximum attachment size', 'Максимальный размер одного вложения в MiB.', data_type='integer', default=150, rules={'min': 1}, order=60),
    _spec('MAIL_GRAPH_MAX_TOTAL_ATTACHMENT_MB', 'mail', 'mail-graph', 'Maximum total attachments', 'Максимальный суммарный размер вложений в MiB.', data_type='integer', default=200, rules={'min': 1}, order=70),
    _spec('MAIL_GRAPH_ALLOWED_EXTENSIONS', 'mail', 'mail-graph', 'Allowed attachment extensions', 'Разделённый запятыми список расширений вложений.', order=80),
    _spec('MAIL_GRAPH_TIMEOUT_SECONDS', 'mail', 'mail-graph', 'Graph request timeout', 'Таймаут запроса Microsoft Graph в секундах.', data_type='float', default=30, rules={'min': 1}, order=90),
    _spec('MAIL_GRAPH_MAX_RETRIES', 'mail', 'mail-graph', 'Graph maximum retries', 'Максимальное число повторов Microsoft Graph.', data_type='integer', default=4, rules={'min': 1, 'max': 20}, order=100),
    _spec('MAIL_GRAPH_OUTBOUND_POLL_SECONDS', 'mail', 'mail-worker', 'Outbound poll interval', 'Интервал опроса outbound-очереди в секундах.', data_type='float', default=2, rules={'min': 0.1}, order=110),
    _spec('MAIL_GRAPH_OUTBOUND_LOCK_SECONDS', 'mail', 'mail-worker', 'Outbound lock duration', 'TTL блокировки outbound-задачи в секундах.', data_type='integer', default=120, rules={'min': 1}, order=120),
    _spec('MAIL_GRAPH_SENT_RECONCILE_TIMEOUT_SECONDS', 'mail', 'mail-worker', 'Sent reconciliation timeout', 'Таймаут подтверждения отправленного письма.', data_type='integer', default=300, rules={'min': 1}, order=130),
    _spec('MAIL_GRAPH_TEMP_TTL_SECONDS', 'mail', 'mail-worker', 'Temporary files TTL', 'TTL временных почтовых файлов в секундах.', data_type='integer', default=86400, rules={'min': 1}, order=140),
    _spec('MAIL_GRAPH_CLAIM_TIMEOUT_SECONDS', 'mail', 'mail-graph', 'Message claim timeout', 'TTL claim сообщения в секундах.', data_type='integer', default=1800, rules={'min': 1}, order=150),
    _spec('MAIL_GRAPH_ALLOWED_DESTINATIONS', 'mail', 'mail-graph', 'Allowed workflow destinations', 'Разделённый запятыми список logical destinations.', default='invoices,error', order=160),
    _spec('MAIL_GRAPH_ATTACHMENT_CACHE_TTL_SECONDS', 'mail', 'mail-graph', 'Attachment cache TTL', 'TTL metadata вложения в секундах.', data_type='integer', default=3600, rules={'min': 1}, order=170),
    _spec('MAIL_GRAPH_TEXT_CACHE_TTL_SECONDS', 'mail', 'mail-graph', 'Text cache TTL', 'TTL извлечённого текста в секундах.', data_type='integer', default=3600, rules={'min': 1}, order=180),
    _spec('MAIL_GRAPH_OCR_LANGUAGES', 'mail', 'mail-graph', 'OCR languages', 'Разделённый запятыми список языков OCR.', default='et,en,ru,fi,sv', order=190),
    _spec('MAIL_GRAPH_OUTBOUND_WORKER_ID', 'mail', 'mail-worker', 'Outbound worker ID', 'Уникальный ID экземпляра worker; задаётся окружением конкретного хоста.', source='env', order=200),
    _spec('MAIL_API_AGENT_KEYS', 'security', 'mail-graph', 'Mail agent API keys', 'Ключи mail agent API; хранятся только в окружении.', source='env', secret=True, order=80),
    _spec('MAIL_API_ADMIN_KEYS', 'security', 'mail-graph', 'Mail admin API keys', 'Ключи mail admin API; хранятся только в окружении.', source='env', secret=True, order=90),
    _spec('MAIL_API_AGENT_POLICIES_JSON', 'security', 'mail-graph', 'Mail agent policies', 'Политики содержат API-ключи и остаются только в окружении.', data_type='json', source='env', secret=True, order=100),
    _spec('MAIL_GRAPH_CLIENT_SECRET', 'security', 'mail-graph', 'Microsoft Graph client secret', 'Client secret Microsoft Graph; хранится только в окружении.', source='env', secret=True, required=True, order=110),

    _spec('MAIL_DIGIDOC_SIVA_URL', 'digidoc', 'mail-graph', 'SiVa endpoint', 'Базовый URL сервиса SiVa.', data_type='url', default='http://127.0.0.1:8085', order=10),
    _spec('MAIL_DIGIDOC_TIMEOUT_SECONDS', 'digidoc', 'mail-graph', 'SiVa timeout', 'Таймаут SiVa в секундах.', data_type='float', default=60, rules={'min': 1}, order=20),
    _spec('MAIL_DIGIDOC_VALIDATION_POLICY', 'digidoc', 'mail-graph', 'SiVa validation policy', 'Политика валидации DigiDoc.', default='POLv4', order=30),
    _spec('MAIL_DIGIDOC_MAX_CONTAINER_MB', 'digidoc', 'mail-graph', 'Maximum DigiDoc container', 'Максимальный размер контейнера в MiB.', data_type='integer', default=20, rules={'min': 1}, order=40),
    _spec('MAIL_GRAPH_MAX_CONTAINER_FILES', 'digidoc', 'mail-graph', 'Maximum container files', 'Максимальное число файлов внутри контейнера.', data_type='integer', default=50, rules={'min': 1}, order=50),
    _spec('MAIL_GRAPH_MAX_CONTAINER_EXPANDED_MB', 'digidoc', 'mail-graph', 'Maximum expanded container', 'Максимальный распакованный размер контейнера в MiB.', data_type='integer', default=100, rules={'min': 1}, order=60),
    _spec('MAIL_GRAPH_ALLOWED_CONTAINER_EXTENSIONS', 'digidoc', 'mail-graph', 'Allowed container extensions', 'Разделённый запятыми список типов DigiDoc-контейнеров.', default='asice,bdoc,ddoc', order=70),
)


PARAMETERS_BY_KEY = {parameter.key: parameter for parameter in PARAMETERS}
_PLACEHOLDER_RE = re.compile(r'^<[^>]+>$')


def parse_env_value(spec: ParameterSpec, raw_value: str | None) -> Any:
    if raw_value is None or raw_value == '':
        raise ValidationError('Value is empty.')
    value = raw_value.strip()
    if _PLACEHOLDER_RE.fullmatch(value):
        raise ValidationError('Value is a placeholder.')

    if spec.data_type == 'integer':
        try:
            return int(value)
        except ValueError as exc:
            raise ValidationError('Value must be an integer.') from exc
    if spec.data_type == 'float':
        try:
            return float(value)
        except ValueError as exc:
            raise ValidationError('Value must be a number.') from exc
    if spec.data_type == 'boolean':
        normalized = value.lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        raise ValidationError('Value must be a boolean.')
    if spec.data_type == 'json':
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValidationError('Value must be valid JSON.') from exc
    return value
