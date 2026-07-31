import pandas as pd
import json
from pathlib import Path

# file locations
current_dir = Path(__file__).resolve().parent
SYSTEM_PATH = 'P:\ROMHacking\SMT IF\PreWork\if备案\if系统文本.xlsx'
TEXT_PATH = 'P:\ROMHacking\SMT IF\PreWork\if备案\翻译.xlsx'
JSON_PATH = current_dir.parent / 'data' / 'text.json'


def read_xl(system_p, text_p):
    df_text = pd.read_excel(text_p, sheet_name='全文本', header=None)
    df_17 = pd.read_excel(text_p, sheet_name='显存字库', header=None)
    df_88 = pd.read_excel(system_p, header=None)

    return df_text, df_17, df_88


def convert_rows(df, translation_col):
    rows = []

    for row in df.to_dict(orient="records"):
        rows.append({
            "id": f'{row[0]}-{row[1]}-{row[2]}',
            "block_offset": row[1],
            "pointer_offset": row[2],
            "source": row[3],
            "translation": row[translation_col]
        })

    return rows


def xl_to_json(df_text, df_17, df_88):
    return {
        "texts": convert_rows(df_text, 5),
        "text_17": convert_rows(df_17, 5),
        "text_88": convert_rows(df_88, 4)
    }


def save_json(data):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print("Json saved to /data/text/json")


if __name__ == "__main__":
    # excel to json
    df_text, df_17, df_88 = read_xl(SYSTEM_PATH, TEXT_PATH)
    save_json(xl_to_json(df_text, df_17, df_88))