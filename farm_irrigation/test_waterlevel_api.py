# 水位接口测试
from waterlevel_api import fetch_waterlevels
rows = fetch_waterlevels(farm_id="13944136728576", unit="mm")
print("返回条数:", len(rows))
print("前3条:"); print(rows[:3])
# 看看每条里 sectionCode 是否都是 None；如果是，大概率是映射文件缺
