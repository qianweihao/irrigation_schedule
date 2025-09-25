#地块id转换
import pandas as pd, json, os

CSV = os.path.join("gzp_farm", "港中坪地块id.csv")
OUT = os.path.join("gzp_farm", "sectionid_2_code.json")

ID_COL = "id"
NAME_COL = "name"

df = pd.read_csv(CSV, encoding="utf-8-sig")
mapping = (df[[ID_COL, NAME_COL]]
           .dropna()
           .astype(str)
           .assign(**{
               ID_COL:   lambda x: x[ID_COL].str.strip(),
               NAME_COL: lambda x: x[NAME_COL].str.strip()
           })
           .drop_duplicates(subset=[ID_COL])
           .set_index(ID_COL)[NAME_COL]
           .to_dict())

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(mapping, f, ensure_ascii=False, indent=2)

print(f"写入完成：{OUT}（共 {len(mapping)} 条）")
