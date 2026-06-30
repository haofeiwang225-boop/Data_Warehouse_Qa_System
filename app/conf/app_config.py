from dataclasses import dataclass
from pathlib import Path

from omegaconf import OmegaConf

@dataclass
class File:
    enable: bool
    level: str
    path: str
    rotation: str
    retention: str

@dataclass
class Console:
    enable: bool
    level: str

@dataclass
class LoggingConfig:
    file: File
    console: Console

# 数据库配置
@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

@dataclass
class QdrantConfig:
    host: str
    port: int
    embedding_size: int

@dataclass
class EmbeddingConfig:
    host: str
    port: int
    model: str

@dataclass
class ESConfig:
    host: str
    port: int
    index_name: str

@dataclass
class LLMConfig:
    model_name: str
    api_key: str
    base_url: str

@dataclass
class AppConfig:
    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig

#把 YAML 文件读进来，变成一个 OmegaConf 的 DictConfig 对象（类似字典）。
config_file = Path(__file__).parents[2] / 'conf' / 'app_config.yaml'


#用你定义的 AppConfig dataclass 生成一个"模板"，规定了配置应该有哪些字段、每个字段是什么类型。
context = OmegaConf.load(config_file) #读取之后就可以类似这样访问：context.db_meta.host
schema = OmegaConf.structured(AppConfig) #根据你定义的 AppConfig dataclass 生成一个配置模板。

app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))