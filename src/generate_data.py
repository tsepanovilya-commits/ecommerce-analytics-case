"""
Генератор синтетических данных интернет-магазина «Уютный дом» (товары для дома).

Зачем: демо-кейс аналитика требует реалистичных данных с заложенными
закономерностями, которые анализ должен «найти»:
  1. Сезонность (пик ноябрь–декабрь, провал летом).
  2. Разное удержание по каналам привлечения (контекст хуже, рефералы лучше).
  3. Аномалия: в 2025-09 у канала 'marketplace_ads' резко падает конверсия
     в повторную покупку (имитация сбоя в рекламной кампании).
  4. A/B-тест (2025-10-01..2025-10-28): порог бесплатной доставки 3000 → 2500 ₽.
     Истинный эффект: +4% к конверсии, -3% к среднему чеку.

Выход: data/customers.csv, data/orders.csv, data/order_items.csv,
       data/products.csv, data/ab_sessions.csv, data/shop.db (SQLite).
Воспроизводимость: фиксированный seed.
"""
import shutil
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
rng = np.random.default_rng(SEED)

# ---------- Справочники ----------
CHANNELS = {  # канал: (доля привлечения, базовая вероятность повторной покупки в месяц)
    "organic": (0.30, 0.10),
    "context_ads": (0.25, 0.06),
    "marketplace_ads": (0.20, 0.08),
    "social": (0.15, 0.07),
    "referral": (0.10, 0.13),
}
REGIONS = ["Москва", "Санкт-Петербург", "Екатеринбург", "Новосибирск", "Казань", "Другие"]
REGION_P = [0.32, 0.18, 0.08, 0.07, 0.06, 0.29]
CATEGORIES = {  # категория: (кол-во SKU, средняя цена, маржинальность)
    "Текстиль": (60, 1800, 0.45),
    "Посуда": (50, 1200, 0.40),
    "Хранение": (40, 900, 0.50),
    "Декор": (45, 1500, 0.55),
    "Освещение": (25, 3200, 0.35),
}
# Сезонный множитель новых клиентов по месяцам (1..12)
SEASON = {1: 0.9, 2: 0.85, 3: 0.95, 4: 0.95, 5: 0.9, 6: 0.75, 7: 0.7,
          8: 0.8, 9: 1.0, 10: 1.1, 11: 1.45, 12: 1.6}


def make_products() -> pd.DataFrame:
    """SKU с ценой (логнормальный разброс вокруг средней) и себестоимостью."""
    rows, pid = [], 1
    for cat, (n, mean_price, margin) in CATEGORIES.items():
        prices = np.round(rng.lognormal(np.log(mean_price), 0.35, n), -1)
        for p in prices:
            rows.append({"product_id": pid, "category": cat, "price": p,
                         "cost": round(p * (1 - margin * rng.uniform(0.85, 1.15)), 2)})
            pid += 1
    return pd.DataFrame(rows)


def make_customers() -> pd.DataFrame:
    """Новые клиенты по месяцам 2024-01..2025-12 с учётом роста и сезонности."""
    months = pd.period_range("2024-01", "2025-12", freq="M")
    rows, cid = [], 1
    for i, m in enumerate(months):
        n = int(1500 * (1 + 0.02 * i) * SEASON[m.month] * rng.normal(1, 0.04))
        ch = rng.choice(list(CHANNELS), n, p=[v[0] for v in CHANNELS.values()])
        rg = rng.choice(REGIONS, n, p=REGION_P)
        days = rng.integers(0, m.days_in_month, n)
        for c, r, d in zip(ch, rg, days):
            rows.append({"customer_id": cid, "signup_date": m.start_time + pd.Timedelta(days=int(d)),
                         "channel": c, "region": r})
            cid += 1
    return pd.DataFrame(rows)


def make_orders(customers: pd.DataFrame, products: pd.DataFrame):
    """Первая покупка в день регистрации, затем помесячные повторные покупки
    с затухающей вероятностью. Здесь же закладывается аномалия 2025-09."""
    end = pd.Timestamp("2025-12-31")
    orders, items, oid = [], [], 1
    prod_arr = products[["product_id", "price"]].to_numpy()
    for c in customers.itertuples(index=False):
        base_p = CHANNELS[c.channel][1]
        date, k = c.signup_date, 0
        while date <= end:
            # --- создать заказ ---
            n_items = rng.choice([1, 2, 3, 4], p=[0.5, 0.3, 0.15, 0.05])
            idx = rng.integers(0, len(prod_arr), n_items)
            qty = rng.choice([1, 2], n_items, p=[0.85, 0.15])
            revenue = 0.0
            for (pid, price), q in zip(prod_arr[idx], qty):
                items.append({"order_id": oid, "product_id": int(pid), "qty": int(q), "price": price})
                revenue += price * q
            orders.append({"order_id": oid, "customer_id": c.customer_id, "order_date": date,
                           "revenue": round(revenue, 2), "status":
                           rng.choice(["delivered", "returned", "cancelled"], p=[0.9, 0.05, 0.05])})
            oid += 1
            # --- следующий заказ: проверяем по месяцам ---
            k += 1
            nxt = None
            for step in range(1, 13):
                cand = date + pd.DateOffset(months=step)
                if cand > end:
                    break
                p = base_p * (0.85 ** (step - 1)) * (1 + 0.1 * min(k, 3))
                if SEASON[cand.month] > 1.3:
                    p *= 1.4  # сезонные распродажи возвращают клиентов
                # Аномалия: сбой в рекламе маркетплейсов в сентябре 2025
                if c.channel == "marketplace_ads" and cand.to_period("M") == pd.Period("2025-09"):
                    p *= 0.35
                if rng.random() < p:
                    nxt = cand + pd.Timedelta(days=int(rng.integers(-10, 10)))
                    break
            if nxt is None or nxt <= date:
                break
            date = nxt
    return pd.DataFrame(orders), pd.DataFrame(items)


def make_ab_sessions() -> pd.DataFrame:
    """Сессии A/B-теста порога бесплатной доставки.
    A (контроль): порог 3000 ₽; B: 2500 ₽. Истинные параметры заданы ниже."""
    n = 60_000
    group = rng.choice(["A", "B"], n)
    conv_p = np.where(group == "A", 0.031, 0.031 * 1.04)
    converted = rng.random(n) < conv_p
    aov_mean = np.where(group == "A", 2900, 2900 * 0.97)
    order_value = np.where(converted, np.round(rng.lognormal(np.log(aov_mean), 0.45), 2), 0)
    dates = pd.Timestamp("2025-10-01") + pd.to_timedelta(rng.integers(0, 28, n), unit="D")
    return pd.DataFrame({"session_id": np.arange(1, n + 1), "session_date": dates,
                         "group": group, "converted": converted.astype(int),
                         "order_value": order_value})


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    products = make_products()
    customers = make_customers()
    orders, items = make_orders(customers, products)
    ab = make_ab_sessions()
    tables = {"products": products, "customers": customers, "orders": orders,
              "order_items": items, "ab_sessions": ab}
    # SQLite не умеет блокировки на сетевых/смонтированных ФС Windows,
    # поэтому база собирается во временной папке и затем копируется.
    tmp_db = Path(tempfile.gettempdir()) / "shop.db"
    with sqlite3.connect(tmp_db) as con:
        for name, df in tables.items():
            df.to_csv(DATA_DIR / f"{name}.csv", index=False)
            df.to_sql(name, con, if_exists="replace", index=False)
    shutil.copyfile(tmp_db, DATA_DIR / "shop.db")
    for name, df in tables.items():
        print(f"{name}: {len(df):,} строк")


if __name__ == "__main__":
    main()
