import re

def _derive_width_cm_from_size(size_str: str):
    """サイズ文字列から接地幅(概算)を cm で返す。
    対応形式:
      メトリック: 225/80R17, 195/65R15 → 先頭3桁(mm)をそのまま幅(mm)とみなし10で割ってcm
      インチ: 11R22.5, 7.50-16, 12.5R20 → 先頭の数値(小数可)をインチとみなし * 2.54 で cm
    パース失敗時は None。
    """
    if not size_str:
        return None
    s = size_str.strip().upper()
    # Metric pattern e.g. 225/80R17
    m_metric = re.match(r"^(\d{3})/(\d{2,3})R\d{2,2}$", s)
    if m_metric:
        width_mm = int(m_metric.group(1))
        return width_mm / 10.0  # mm -> cm (簡易近似)
    # Inch pattern e.g. 11R22.5 or 7.50-16 or 12.5R20
    m_inch_r = re.match(r"^(\d+(?:\.\d+)?)R\d+(?:\.\d+)?$", s)
    if m_inch_r:
        width_in = float(m_inch_r.group(1))
        return width_in * 2.54
    m_inch_dash = re.match(r"^(\d+(?:\.\d+)?)\-\d+(?:\.\d+)?$", s)
    if m_inch_dash:
        width_in = float(m_inch_dash.group(1))
        return width_in * 2.54
    return None

def compute_weight_metrics(vw, ml, fa, ra, tire_count, tire_load_per_tire, contact_width_cm,
                           front_tire_size: str = None, rear_tire_size: str = None):
    """重量計算: 入力値 + タイヤサイズから各指標を算出し辞書で返す。
    contact_width_cm が 0 以下の場合、サイズから派生した幅を採用。
    タイヤサイズ形式: 例 '225/80R17'. パースできない場合はサイズ由来幅は使用しない。"""
    total_weight = vw + ml
    if tire_count <= 0 or tire_load_per_tire <= 0:
        raise ValueError("タイヤ本数/荷重は正の数値")

    # 前後輪の接地幅決定
    front_width_cm = contact_width_cm if contact_width_cm and contact_width_cm > 0 else _derive_width_cm_from_size(front_tire_size or '')
    rear_width_cm = contact_width_cm if contact_width_cm and contact_width_cm > 0 else _derive_width_cm_from_size(rear_tire_size or '')

    # 派生できなかった場合は contact_width_cm が非正でもエラー
    if front_width_cm is None or rear_width_cm is None:
        raise ValueError("接地幅未入力でサイズから幅を導出できませんでした。形式例: 225/80R17")

    front_strength_ratio = fa / (tire_count / 2 * tire_load_per_tire)
    rear_strength_ratio = ra / (tire_count / 2 * tire_load_per_tire)
    front_contact_pressure = fa / ((front_width_cm / 100) * (tire_count / 2))
    rear_contact_pressure = ra / ((rear_width_cm / 100) * (tire_count / 2))
    return {
        "total_weight": total_weight,
        "front_strength_ratio": front_strength_ratio,
        "rear_strength_ratio": rear_strength_ratio,
        "front_contact_pressure": front_contact_pressure,
        "rear_contact_pressure": rear_contact_pressure,
        "front_contact_width_cm_used": front_width_cm,
        "rear_contact_width_cm_used": rear_width_cm,
    }
