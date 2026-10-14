"""
Анализ данных магазина «Уютный дом»: выполняет SQL из sql/, строит графики,
считает A/B-тест и сохраняет результаты в output/.

Запуск: python src/analyze.py   (после src/generate_data.py)
"""
import shutil
import sqlite3
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
SQL, OUT = ROOT / "sql", ROOT / "output"
OUT.mkdir(exist_ok=True)


def run_sql(con, name: str) -> pd.DataFrame:
    """Выполнить SQL-файл и сохранить результат в CSV."""
    df = pd.read_sql_query((SQL / name).read_text(encoding="utf-8"), con)
    df.to_csv(OUT / name.replace(".sql", ".csv"), index=False)
    return df


def ab_test(ab: pd.DataFrame) -> dict:
    """Конверсия: z-тест для долей. Средний чек: t-тест Уэлча.
    Выручка на сессию: бутстрэп-доверительный интервал разницы."""
    a, b = ab[ab.group == "A"], ab[ab.group == "B"]
    ca, cb = a.converted.mean(), b.converted.mean()
    p_pool = ab.converted.mean()
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / len(a) + 1 / len(b)))
    z = (cb - ca) / se
    p_conv = 2 * (1 - stats.norm.cdf(abs(z)))
    aov_a, aov_b = a.order_value[a.converted == 1], b.order_value[b.converted == 1]
    p_aov = stats.ttest_ind(aov_a, aov_b, equal_var=False).pvalue
    rng = np.random.default_rng(0)
    va, vb = a.order_value.to_numpy(), b.order_value.to_numpy()
    boots = [rng.choice(vb, len(vb)).mean() - rng.choice(va, len(va)).mean() for _ in range(2000)]
    return {"n_A": len(a), "n_B": len(b), "conv_A": ca, "conv_B": cb,
            "conv_uplift": cb / ca - 1, "p_conv": p_conv,
            "aov_A": aov_a.mean(), "aov_B": aov_b.mean(), "p_aov": p_aov,
            "rps_A": va.mean(), "rps_B": vb.mean(),
            "rps_diff_ci": (np.percentile(boots, 2.5), np.percentile(boots, 97.5)),
            # Мощность: сколько сессий нужно на группу для MDE +4% при alpha=.05, power=.8
            "n_needed": int(2 * ((1.96 + 0.84) ** 2) * ca * (1 - ca) / (ca * 0.04) ** 2)}


def main():
    # копия БД во временную папку: SQLite нестабилен на смонтированных ФС
    tmp = Path(tempfile.gettempdir()) / "shop_ro.db"
    shutil.copyfile(ROOT / "data" / "shop.db", tmp)
    with sqlite3.connect(tmp) as con:
        kpi = run_sql(con, "01_monthly_kpi.sql")
        coh = run_sql(con, "02_cohort_retention.sql")
        ch = run_sql(con, "03_channel_repeat_monthly.sql")
        rfm = run_sql(con, "04_rfm.sql")
        cat = run_sql(con, "05_category_margin.sql")
        ab = pd.read_sql_query("SELECT * FROM ab_sessions", con)

    # --- 1. Выручка по месяцам ---
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(kpi.month, kpi.revenue / 1e6, color="#4C72B0")
    ax.set_title("Выручка по месяцам, млн ₽"); ax.tick_params(axis="x", rotation=90)
    fig.tight_layout(); fig.savefig(OUT / "revenue_monthly.png", dpi=80); plt.close(fig)

    # --- 2. Тепловая карта когорт (2024 г., M0..M12) ---
    piv = coh[coh.cohort < "2025-01"].pivot(index="cohort", columns="month_n", values="retention")
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(piv.iloc[:, 1:], cmap="Blues", aspect="auto")
    ax.set_yticks(range(len(piv))); ax.set_yticklabels(piv.index)
    ax.set_xticks(range(len(piv.columns) - 1)); ax.set_xticklabels(piv.columns[1:])
    ax.set_xlabel("Месяц после регистрации"); ax.set_title("Когортное удержание (M1–M12)")
    fig.colorbar(im); fig.tight_layout(); fig.savefig(OUT / "cohorts.png", dpi=80); plt.close(fig)

    # --- 3. Удержание M1–M3 по каналам ---
    with sqlite3.connect(tmp) as con:
        ret_ch = pd.read_sql_query("""
            SELECT c.channel,
                   ROUND(1.0*COUNT(DISTINCT CASE WHEN julianday(o.order_date)-julianday(c.signup_date)
                         BETWEEN 15 AND 105 THEN c.customer_id END)/COUNT(DISTINCT c.customer_id),4) AS repeat_90d
            FROM customers c JOIN orders o USING(customer_id)
            WHERE c.signup_date < '2025-09-01' GROUP BY c.channel ORDER BY repeat_90d DESC""", con)
    ret_ch.to_csv(OUT / "channel_repeat_90d.csv", index=False)

    # --- 4. Аномалии: отклонение > 35% от скользящего среднего ---
    anomalies = ch[ch.deviation < -0.35]
    anomalies.to_csv(OUT / "anomalies.csv", index=False)
    fig, ax = plt.subplots(figsize=(10, 4))
    for name, g in ch.groupby("channel"):
        ax.plot(g.month, g.repeat_orders, label=name, lw=2 if name == "marketplace_ads" else 1)
    ax.legend(); ax.set_title("Повторные заказы по каналам"); ax.tick_params(axis="x", rotation=90)
    fig.tight_layout(); fig.savefig(OUT / "channel_repeat.png", dpi=80); plt.close(fig)

    # --- 5. A/B-тест ---
    res = ab_test(ab)
    pd.Series(res).to_csv(OUT / "ab_test.csv", header=["value"])

    # --- Сводка для отчёта ---
    print("KPI 2025 vs 2024:")
    y = kpi.assign(year=kpi.month.str[:4]).groupby("year")[["revenue", "orders"]].sum()
    print(y, "\nрост выручки:", round(y.revenue.iloc[1] / y.revenue.iloc[0] - 1, 3))
    print("\nСредний чек:", kpi.aov.mean())
    print("\nПовтор 90 дней по каналам:\n", ret_ch)
    print("\nАномалии:\n", anomalies)
    print("\nRFM:\n", rfm)
    print("\nКатегории:\n", cat)
    print("\nM1/M3/M6 средние:", coh.groupby("month_n").retention.mean().loc[[1, 3, 6]].round(4).to_dict())
    print("\nA/B:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()})


if __name__ == "__main__":
    main()
