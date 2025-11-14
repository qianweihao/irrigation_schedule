# 实时水位数据获取
import os
import json
import requests
from functools import lru_cache

# ===== 接口环境配置（可用 ENV 覆盖）=====
CURRENT_ENV = os.environ.get('ENV_API_RICE_IRRIGATION', 'DEV')

if CURRENT_ENV == 'DEV':
    BASE_URL = "https://iland.zoomlion.com"
    TOKEN = "myUmUUaE9uLEWvzgGpamlYfc1WfsusPB"
elif CURRENT_ENV == 'BETA':
    BASE_URL = "http://emng-test.zoomlion.com"
    TOKEN = "kFceK62qazYkDjJeYAGiT5W2mW1iRuDe"
elif CURRENT_ENV == 'PRODUCTION':
    BASE_URL = "https://iland.zoomlion.com"
    TOKEN = "myUmUUaE9uLEWvzgGpamlYfc1WfsusPB"
else:
    BASE_URL = "https://iland.zoomlion.com"
    TOKEN = "myUmUUaE9uLEWvzgGpamlYfc1WfsusPB"

# 允许环境变量覆盖
BASE_URL = os.environ.get("RICE_IRRIGATION_BASE_URL", BASE_URL)
TOKEN    = os.environ.get("RICE_IRRIGATION_TOKEN", TOKEN)

ENDPOINT = f"{BASE_URL}/open-sharing-platform/zlapi/irrigationApi/v1/getWaterLastByFarm"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": TOKEN,
}
TIMEOUT = 15  # 秒

def _mapping_path() -> str:
    """
    返回映射文件路径：
    - 优先环境变量 SECTIONID_CODE_PATH 指定的路径
    - 否则使用项目根目录下的 data/gzp_farm/sectionid_2_code.json
    """
    if os.environ.get("SECTIONID_CODE_PATH"):
        return os.environ["SECTIONID_CODE_PATH"]
    # 从当前文件位置向上找到项目根目录（包含 data/ 目录的目录）
    here = os.path.dirname(os.path.abspath(__file__))
    # 当前文件在 src/api/，向上两级到项目根目录
    project_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(project_root, "data", "gzp_farm", "sectionid_2_code.json")

def _normalize_sid(x) -> str:
    return str(x).strip()

def _normalize_code(x) -> str:
    s = str(x).strip()
    return s.lstrip("0") or "0"

@lru_cache(maxsize=1)
def _load_sectionid_to_code() -> dict:
    """
    读取 sectionID -> sectionCode 映射（缓存）。要求 JSON 形如：
      { "<sectionID>": "<sectionCode>", ... }
    也兼容值为对象的情况：{"code": "..."} 或 {"编号": "..."} 或 {"name": "..."}。
    """
    path = _mapping_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        # 映射缺失则返回空，调用处会将 sectionCode 置为 None
        return {}

    if not isinstance(raw, dict):
        return {}

    mapping = {}
    for k, v in raw.items():
        sid = _normalize_sid(k)
        if isinstance(v, dict):
            code_val = v.get("sectionCode") or v.get("code") or v.get("编号") or v.get("name")
            if code_val is None:
                continue
            mapping[sid] = _normalize_code(code_val)
        else:
            mapping[sid] = _normalize_code(v)
    return mapping

def fetch_waterlevels(farm_id: str, unit: str = "mm"):
    """
    获取农场所有田块水位，并通过 gzp_farm/sectionid_2_code.json 映射出 sectionCode。
    返回：list[{"sectionID": str, "sectionCode": str|None, "waterlevel_mm": float}]
    """
    # 1) 请求真实数据
    r = requests.get(ENDPOINT, headers=HEADERS, params={"farmID": str(farm_id)}, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []

    # 2) 读取映射
    id2code = _load_sectionid_to_code()

    # 3) 组装输出
    out = []
    for it in data:
        sid = it.get("sectionID")
        if sid is None:
            continue
        sid_str = _normalize_sid(sid)

        # liquidLevelValue 通常为 cm
        try:
            wl_cm = float(it.get("liquidLevelValue", 0.0))
        except (TypeError, ValueError):
            wl_cm = 0.0
        wl_val = wl_cm * 10.0 if unit == "mm" else wl_cm

        code = id2code.get(sid_str)  # 若映射缺少该 sid，则为 None
        out.append({
            "sectionID": sid_str,
            "sectionCode": code if code is not None else None,
            "waterlevel_mm": float(wl_val),
        })

    return out
