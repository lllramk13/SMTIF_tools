import json
from pathlib import Path
from src.codetable import read_json, write_json

current_dir = Path(__file__).resolve().parent

CONTROL_CODES = {
    "{00FF}": "00FF",
    "▽": "01FF",
    "※※※※※※※": "02FF",
    "\n": "03FF",
    "{主角}": "04FF",
    "{队友}": "05FF",
    "{名字1}": "18FF",
    "{名字4}": "19FF",
    "{道具}": "1BFF",
    "{种族1}": "67FF",
    "{种族2}": "68FF",
    "{主角等人}": "6FFF",
    "{仲魔}": "70FF",
    "{数值0}": "71FF",
    "{72FF}": "72FF",
    "{73FF}": "73FF",
    "{数值1}": "76FF",
    "{名字3}": "77FF",
    "{种族3}": "78FF",
    "{恶魔1}": "7AFF",
    "{魔法}": "7BFF",
    "/": "7CFF",
    "{名字2}": "7DFF",
    "{恶魔2}": "7FFF",
    "{数量}": "88FF",
    "{大停顿}": "92FF",
    "　": "FEFF",
}


def load_character_codes(codetable_path):
    data = read_json(codetable_path)
    reversed_table = {value: bytes.fromhex(key) for key, value in data.items()}
    return reversed_table


def encode_text(character_codes, text):
    output = bytearray()
    position = 0

    control_codes = {
        token: bytes.fromhex(code) if isinstance(code, str) else code
        for token, code in CONTROL_CODES.items()
    }

    while position < len(text):
        character = text[position]

        if character == "{":
            closing_position = text.find("}", position + 1)
            if closing_position == -1:
                raise ValueError(f"未闭合的控制符，位置: {position}")

            token = text[position:closing_position + 1]
            code = control_codes.get(token)

            if code is None:
                raise ValueError(f"未知控制符 {token!r}，位置: {position}")

            output.extend(code)
            position = closing_position + 1

        elif character == "▽":
            output.extend(control_codes["▽"])
            position += 1
            if position < len(text) and text[position] == "\n":
                position += 1

        elif character == "※":
            marker = "※※※※※※※"
            if text.startswith(marker, position):
                output.extend(control_codes[marker])
                position += len(marker)
                if position < len(text) and text[position] == "\n":
                    position += 1
                continue

            code = character_codes.get(character)
            if code is None:
                raise ValueError(f"字符 {character!r} 不在码表中，位置: {position}")

            if isinstance(code, str):
                code = bytes.fromhex(code)
            output.extend(code)
            position += 1

        elif character == "\n":
            output.extend(control_codes["\n"])
            position += 1

        elif character == "/":
            output.extend(control_codes["/"])
            position += 1

        elif character == "　":
            output.extend(control_codes["　"])
            position += 1

        elif character == "}":
            raise ValueError(f"没有对应左括号的 }}，位置: {position}")

        else:
            code = character_codes.get(character)
            if code is None:
                raise ValueError(f"字符 {character!r} 不在码表中，位置: {position}")

            if isinstance(code, str):
                code = bytes.fromhex(code)
            output.extend(code)
            position += 1

    output.extend(b"\xFF\xFF")
    return bytes(output)
