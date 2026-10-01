from advisor import load_rules, verdict

m = {"price": 110, "vwap": 100, "rsi": 60, "pe": None}
sec = {"default": "HOLD", "BUY": [["price", ">", "vwap"], ["rsi", "between", [50, 70]]], "SELL": [["price", "<", "vwap"]]}

assert verdict(sec, m)["verdict"] == "BUY"
assert verdict(sec, {**m, "rsi": 80})["verdict"] == "HOLD"  # one failing rule blocks BUY
assert verdict(sec, {**m, "price": 90})["verdict"] == "SELL"
assert verdict({"default": "X", "BUY": [["pe", "<", 30]]}, m)["verdict"] == "X"  # missing metric fails, no crash
assert verdict({"default": "X", "BUY": [["nope", ">", "vwap"]]}, m)["verdict"] == "X"

for bad in ['[a]\nBUY = [["rsi", "~", 3]]', '[a]\nBUY = [["rsi", "between", 3]]', '[a]\nBUY = "x"', "[a"]:
    try:
        load_rules(bad)
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
print("ok")
