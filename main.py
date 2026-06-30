import uuid
from urllib.request import Request

from fastapi import FastAPI
from loguru import logger
from app.api.lifespan import lifespan
from app.api.routers.query_router import query_router
from app.core.context import request_id_ctx_var

app = FastAPI(lifespan=lifespan)
app.include_router(query_router)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # 调用路径函数之前
    request_id_ctx_var.set(uuid.uuid4())
    # 调用路径函数
    response = await call_next(request)
    # 调用路径函数之后
    return response


def main():
    logger.info("Starting.....")
    logger.warning("Warning...")
    logger.error("Error...")


if __name__ == "__main__":
    main()
