import math

# 車枠(梯形/長方形中抜き)断面を単純化して強度計算
# 入力:
#   weights: 荷重点のリスト [kg] 6点 (符号付き; 下向き荷重を正)
#   distances: 隣接荷重点間距離リスト [mm] 5区間
#   B,H,b,h: 外形幅B, 外形高さH, 内側(抜き部)幅b, 内側高さh (mm)
#   tensile: 引張強さ θb [kg/cm^2]
#   yield_pt: 降伏点 θy [kg/cm^2]
# 出力 dict:
#   shear_list: 各区間開始位置でのせん断力 (kg)
#   moment_list: 各区間終端での曲げモーメント (kg*cm)
#   Mmax: 最大曲げモーメント (kg*cm)
#   Z_mm3: 断面係数 (mm^3)
#   Z_cm3: 断面係数 (cm^3)
#   sigma: 曲げ応力 (kg/cm^2)
#   sf_break, sf_yield, ok_break, ok_yield
# 計算モデル:
#   せん断力: 荷重累積和。
#   曲げモーメント: 各区間長 (cm) × 区間開始時せん断力。
#   断面係数: (B*H**3 - b*h**3) / (6*H) (中抜き長方形近似)。
#   応力: sigma = Mmax / Z_cm3。
#   安全率: θ / (2.5 * sigma) とし破断>1.6, 降伏>1.3 基準。

def compute_frame_strength(weights, distances, B, H, b, h, tensile, yield_pt):
    if len(weights) != 6 or len(distances) != 5:
        raise ValueError("weightsは6点, distancesは5区間を指定")
    # 基本入力チェック
    for val in [B,H,b,h,tensile,yield_pt] + weights + distances:
        if val <= 0:
            raise ValueError("正の値を入力してください (荷重は符号許容だが絶対値>0)")
    # せん断力計算
    shear_list = []
    shear = 0.0
    for w in weights:
        shear += w
        shear_list.append(shear)
    # 曲げモーメント計算
    # 区間 i は荷重点 i と i+1 の間: その区間開始時のせん断= shear_list[i]
    moment_list = []
    for i, dist_mm in enumerate(distances):
        dist_cm = dist_mm / 10.0
        M = shear_list[i] * dist_cm  # kg*cm
        moment_list.append(M)
    Mmax = max(abs(m) for m in moment_list)
    # 断面係数 (mm^3)
    Z_mm3 = (B * (H**3) - b * (h**3)) / (6.0 * H)
    Z_cm3 = Z_mm3 / 1000.0  # 1 cm^3 = 1000 mm^3
    sigma = Mmax / Z_cm3  # kg/cm^2
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        cross_type='rect_hollow',
    )


def compute_container_frame_strength(container_weight, span_len_mm, front_offset_mm, rear_offset_mm,
                                     B, H, b, h, tensile, yield_pt):
    """コンテナ4点支持シャーシ用の簡易車枠強度計算。

    モデル: 2本の縦桁にコンテナ重量を4点(各桁2点)で支持。
    縦桁1本あたり荷重はコンテナ総重量の 1/2 (左右均等支持仮定)。
    1本の縦桁上に2点荷重 P1=P2=コンテナ重量/4 が front_offset, span_len - rear_offset 位置に作用。
    両端単純支持とし、端部反力 R1, R2 を静的釣り合いから算出。
    せん断力は区間ごとのステップ (R1, R1-P1, R1-P1-P2=-R2) を返す。
    曲げモーメントは区間長×区間開始せん断力の積を累積し M1, M2, M3 (終端で0に戻る) を算出。
    最大曲げモーメント Mmax = max(|M1|, |M2|)。
    断面係数・応力・安全率は既存式を流用。

    単純化の留意点:
      - 横方向荷重分布偏り, 捩り, 横桁剛性は無視。
      - 荷重位置はオフセット指定位置に集中荷重として扱う。
      - front_offset + rear_offset < span_len 前提。
    """
    for val in [container_weight, span_len_mm, front_offset_mm, rear_offset_mm, B, H, b, h, tensile, yield_pt]:
        if val <= 0:
            raise ValueError('正の値を入力してください。')
    if front_offset_mm + rear_offset_mm >= span_len_mm:
        raise ValueError('前後オフセットの合計がスパン長以上です。配置を見直してください。')
    # 荷重 (kg)
    P_total_beam = container_weight / 2.0  # 1本の縦桁に載る総荷重
    P1 = P2 = P_total_beam / 2.0
    L_mm = span_len_mm
    a_mm = front_offset_mm
    b_mm = rear_offset_mm
    # 反力 (静的釣り合い)
    # R2*L = P1*(L - a) + P2*(b)
    L = L_mm
    R2 = (P1 * (L - a_mm) + P2 * b_mm) / L
    R1 = P1 + P2 - R2
    # 区間長 (mm)
    mid_len_mm = L_mm - a_mm - b_mm
    # せん断力ステップ (kg)
    shear_list = [R1, R1 - P1, R1 - P1 - P2]  # 最終は -R2
    # 曲げモーメント累積計算 (kg*cm)
    a_cm = a_mm / 10.0
    mid_cm = mid_len_mm / 10.0
    b_cm = b_mm / 10.0
    M1 = shear_list[0] * a_cm
    M2 = M1 + shear_list[1] * mid_cm
    M3 = M2 + shear_list[2] * b_cm  # 終端 (0 付近)
    moment_list = [M1, M2, M3]
    Mmax = max(abs(M1), abs(M2))
    # 断面係数
    Z_mm3 = (B * (H**3) - b * (h**3)) / (6.0 * H)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        # 追加情報
        mode='container4',
        P1=P1,
        P2=P2,
        R1=R1,
        R2=R2,
        span_len_mm=span_len_mm,
        front_offset_mm=front_offset_mm,
        rear_offset_mm=rear_offset_mm,
        cross_type='rect_hollow',
    )


def compute_container_frame_strength_axles(container_weight, span_len_mm,
                                           front_offset_mm, rear_offset_mm,
                                           axle1_pos_mm, axle2_pos_mm,
                                           B, H, b, h, tensile, yield_pt):
    """コンテナ4点支持 + 任意支点(車軸)位置モデル。"""
    for val in [container_weight, span_len_mm, front_offset_mm, rear_offset_mm, axle1_pos_mm, axle2_pos_mm, B, H, b, h, tensile, yield_pt]:
        if val <= 0:
            raise ValueError('正の値を入力してください。')
    if axle1_pos_mm >= axle2_pos_mm:
        raise ValueError('前側支点位置は後側支点位置より小さくしてください。')
    if axle2_pos_mm >= span_len_mm:
        raise ValueError('後側支点位置がスパン長を超えています。')
    xP1 = front_offset_mm
    xP2 = span_len_mm - rear_offset_mm
    if xP1 < axle1_pos_mm or xP2 > axle2_pos_mm:
        raise ValueError('荷重が支点範囲外です。支点内に荷重が入るよう調整してください。')
    P_total_beam = container_weight / 2.0
    P1 = P2 = P_total_beam / 2.0
    xA = axle1_pos_mm
    xB = axle2_pos_mm
    R2 = (P1 * (xB - xP1) + P2 * (xB - xP2)) / (xB - xA)
    R1 = P1 + P2 - R2
    d1 = xP1 - xA
    d2 = xP2 - xP1
    d3 = xB - xP2
    if min(d1, d2, d3) < 0:
        raise ValueError('区間長が負になりました。入力関係を確認してください。')
    shear_list = [R1, R1 + P1, R1 + P1 + P2]
    d1_cm = d1 / 10.0
    d2_cm = d2 / 10.0
    d3_cm = d3 / 10.0
    M1 = shear_list[0] * d1_cm
    M2 = M1 + shear_list[1] * d2_cm
    M3 = M2 + shear_list[2] * d3_cm
    moment_list = [M1, M2, M3]
    Mmax = max(abs(M1), abs(M2))
    Z_mm3 = (B * (H**3) - b * (h**3)) / (6.0 * H)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        mode='container4_axles',
        P1=P1,
        P2=P2,
        R1=R1,
        R2=R2,
        span_len_mm=span_len_mm,
        front_offset_mm=front_offset_mm,
        rear_offset_mm=rear_offset_mm,
        axle1_pos_mm=axle1_pos_mm,
        axle2_pos_mm=axle2_pos_mm,
        dists=[d1, d2, d3],
        cross_type='rect_hollow',
    )

# ==== H形鋼(Ｉビーム)断面対応追加関数 ====
# 断面係数 Z_mm3: I = (B*H^3 - (B - tw)*(H - 2*tf)^3) / 12, Z = 2I / H
def _hbeam_Z_mm3(B, H, tw, tf):
    if min(B, H, tw, tf) <= 0:
        raise ValueError('H形鋼寸法は正の値を入力してください。')
    if 2 * tf >= H:
        raise ValueError('フランジ厚 tf が全高さ H に対して大きすぎます。')
    if tw >= B:
        raise ValueError('ウェブ厚 tw がフランジ幅 B 以上です。')
    I = (B * (H**3) - (B - tw) * ((H - 2 * tf)**3)) / 12.0
    Z_mm3 = 2.0 * I / H
    return Z_mm3

def compute_frame_strength_hbeam(weights, distances, B, H, tw, tf, tensile, yield_pt):
    if len(weights) != 6 or len(distances) != 5:
        raise ValueError('weightsは6点, distancesは5区間を指定')
    for val in [B, H, tw, tf, tensile, yield_pt] + weights + distances:
        if val <= 0:
            raise ValueError('正の値を入力してください')
    shear_list = []
    shear = 0.0
    for w in weights:
        shear += w
        shear_list.append(shear)
    moment_list = []
    for i, dist_mm in enumerate(distances):
        dist_cm = dist_mm / 10.0
        moment_list.append(shear_list[i] * dist_cm)
    Mmax = max(abs(m) for m in moment_list)
    Z_mm3 = _hbeam_Z_mm3(B, H, tw, tf)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        cross_type='hbeam',
    )

def compute_container_frame_strength_hbeam(container_weight, span_len_mm, front_offset_mm, rear_offset_mm,
                                           B, H, tw, tf, tensile, yield_pt):
    for val in [container_weight, span_len_mm, front_offset_mm, rear_offset_mm, B, H, tw, tf, tensile, yield_pt]:
        if val <= 0:
            raise ValueError('正の値を入力してください。')
    if front_offset_mm + rear_offset_mm >= span_len_mm:
        raise ValueError('前後オフセットの合計がスパン長以上です。')
    P_total_beam = container_weight / 2.0
    P1 = P2 = P_total_beam / 2.0
    L = span_len_mm
    a = front_offset_mm
    b = rear_offset_mm
    R2 = (P1 * (L - a) + P2 * b) / L
    R1 = P1 + P2 - R2
    mid_len_mm = L - a - b
    shear_list = [R1, R1 - P1, R1 - P1 - P2]
    a_cm = a / 10.0
    mid_cm = mid_len_mm / 10.0
    b_cm = b / 10.0
    M1 = shear_list[0] * a_cm
    M2 = M1 + shear_list[1] * mid_cm
    M3 = M2 + shear_list[2] * b_cm
    moment_list = [M1, M2, M3]
    Mmax = max(abs(M1), abs(M2))
    Z_mm3 = _hbeam_Z_mm3(B, H, tw, tf)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        mode='container4',
        P1=P1,
        P2=P2,
        R1=R1,
        R2=R2,
        span_len_mm=span_len_mm,
        front_offset_mm=front_offset_mm,
        rear_offset_mm=rear_offset_mm,
        cross_type='hbeam'
    )

def compute_container_frame_strength_axles_hbeam(container_weight, span_len_mm,
                                                 front_offset_mm, rear_offset_mm,
                                                 axle1_pos_mm, axle2_pos_mm,
                                                 B, H, tw, tf, tensile, yield_pt):
    for val in [container_weight, span_len_mm, front_offset_mm, rear_offset_mm, axle1_pos_mm, axle2_pos_mm, B, H, tw, tf, tensile, yield_pt]:
        if val <= 0:
            raise ValueError('正の値を入力してください。')
    if axle1_pos_mm >= axle2_pos_mm:
        raise ValueError('支点順序 X1 < X2 を満たしてください。')
    if axle2_pos_mm >= span_len_mm:
        raise ValueError('X2 が L を超えています。')
    xP1 = front_offset_mm
    xP2 = span_len_mm - rear_offset_mm
    if xP1 < axle1_pos_mm or xP2 > axle2_pos_mm:
        raise ValueError('荷重位置が支点範囲外です。')
    P_total_beam = container_weight / 2.0
    P1 = P2 = P_total_beam / 2.0
    xA = axle1_pos_mm
    xB = axle2_pos_mm
    R2 = (P1 * (xB - xP1) + P2 * (xB - xP2)) / (xB - xA)
    R1 = P1 + P2 - R2
    d1 = xP1 - xA
    d2 = xP2 - xP1
    d3 = xB - xP2
    shear_list = [R1, R1 + P1, R1 + P1 + P2]
    d1_cm = d1 / 10.0
    d2_cm = d2 / 10.0
    d3_cm = d3 / 10.0
    M1 = shear_list[0] * d1_cm
    M2 = M1 + shear_list[1] * d2_cm
    M3 = M2 + shear_list[2] * d3_cm
    moment_list = [M1, M2, M3]
    Mmax = max(abs(M1), abs(M2))
    Z_mm3 = _hbeam_Z_mm3(B, H, tw, tf)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        mode='container4_axles',
        P1=P1,
        P2=P2,
        R1=R1,
        R2=R2,
        span_len_mm=span_len_mm,
        front_offset_mm=front_offset_mm,
        rear_offset_mm=rear_offset_mm,
        axle1_pos_mm=axle1_pos_mm,
        axle2_pos_mm=axle2_pos_mm,
        dists=[d1, d2, d3],
        cross_type='hbeam'
    )

# ==== 支点が荷重間にあるモデル (X1, X2 を a と L-b の間に配置) ====
def compute_container_frame_strength_supports_inside(container_weight, span_len_mm,
                                                    front_offset_mm, rear_offset_mm,
                                                    X1_mm, X2_mm,
                                                    B, H, b, h, tensile, yield_pt):
    for val in [container_weight, span_len_mm, front_offset_mm, rear_offset_mm, X1_mm, X2_mm, B, H, b, h, tensile, yield_pt]:
        if val <= 0:
            raise ValueError('正の値を入力してください。')
    L = span_len_mm
    xP1 = front_offset_mm
    xP2 = L - rear_offset_mm
    if not (xP1 < X1_mm < X2_mm < xP2):
        raise ValueError('支点は a と (L-b) の間に配置してください。条件: a < X1 < X2 < L-b')
    # 荷重 (縦桁1本)
    P_total_beam = container_weight / 2.0
    P1 = P2 = P_total_beam / 2.0
    # 反力
    R2 = (P1 * (X1_mm - xP1) + P2 * (xP2 - X1_mm)) / (X2_mm - X1_mm)
    R1 = P1 + P2 - R2
    # 区間長: [xP1->X1], [X1->X2], [X2->xP2]
    d1 = X1_mm - xP1
    d2 = X2_mm - X1_mm
    d3 = xP2 - X2_mm
    d1_cm = d1 / 10.0
    d2_cm = d2 / 10.0
    d3_cm = d3 / 10.0
    # せん断ステップ (各区間開始値)
    shear_list = [P1, P1 + R1, P1 + R1 + R2]
    # 曲げモーメント累積 (区間開始せん断 × 区間長)
    M1 = shear_list[0] * d1_cm
    M2 = M1 + shear_list[1] * d2_cm
    M3 = M2 + shear_list[2] * d3_cm
    moment_list = [M1, M2, M3]
    Mmax = max(abs(M1), abs(M2), abs(M3))
    # 断面係数
    Z_mm3 = (B * (H**3) - b * (h**3)) / (6.0 * H)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        mode='container4_supports_inside',
        P1=P1, P2=P2, R1=R1, R2=R2,
        span_len_mm=span_len_mm,
        front_offset_mm=front_offset_mm,
        rear_offset_mm=rear_offset_mm,
        axle1_pos_mm=X1_mm,
        axle2_pos_mm=X2_mm,
        dists=[d1, d2, d3],
        cross_type='rect_hollow',
    )

def compute_container_frame_strength_supports_inside_hbeam(container_weight, span_len_mm,
                                                           front_offset_mm, rear_offset_mm,
                                                           X1_mm, X2_mm,
                                                           B, H, tw, tf, tensile, yield_pt):
    for val in [container_weight, span_len_mm, front_offset_mm, rear_offset_mm, X1_mm, X2_mm, B, H, tw, tf, tensile, yield_pt]:
        if val <= 0:
            raise ValueError('正の値を入力してください。')
    L = span_len_mm
    xP1 = front_offset_mm
    xP2 = L - rear_offset_mm
    if not (xP1 < X1_mm < X2_mm < xP2):
        raise ValueError('支点は a と (L-b) の間に配置してください。条件: a < X1 < X2 < L-b')
    P_total_beam = container_weight / 2.0
    P1 = P2 = P_total_beam / 2.0
    R2 = (P1 * (X1_mm - xP1) + P2 * (xP2 - X1_mm)) / (X2_mm - X1_mm)
    R1 = P1 + P2 - R2
    d1 = X1_mm - xP1
    d2 = X2_mm - X1_mm
    d3 = xP2 - X2_mm
    d1_cm = d1 / 10.0
    d2_cm = d2 / 10.0
    d3_cm = d3 / 10.0
    shear_list = [P1, P1 + R1, P1 + R1 + R2]
    M1 = shear_list[0] * d1_cm
    M2 = M1 + shear_list[1] * d2_cm
    M3 = M2 + shear_list[2] * d3_cm
    moment_list = [M1, M2, M3]
    Mmax = max(abs(M1), abs(M2), abs(M3))
    Z_mm3 = _hbeam_Z_mm3(B, H, tw, tf)
    Z_cm3 = Z_mm3 / 1000.0
    sigma = Mmax / Z_cm3
    factor = 2.5
    sf_break = tensile / (factor * sigma)
    sf_yield = yield_pt / (factor * sigma)
    ok_break = sf_break > 1.6
    ok_yield = sf_yield > 1.3
    return dict(
        shear_list=shear_list,
        moment_list=moment_list,
        Mmax=Mmax,
        Z_mm3=Z_mm3,
        Z_cm3=Z_cm3,
        sigma=sigma,
        sf_break=sf_break,
        sf_yield=sf_yield,
        ok_break=ok_break,
        ok_yield=ok_yield,
        mode='container4_supports_inside',
        P1=P1, P2=P2, R1=R1, R2=R2,
        span_len_mm=span_len_mm,
        front_offset_mm=front_offset_mm,
        rear_offset_mm=rear_offset_mm,
        axle1_pos_mm=X1_mm,
        axle2_pos_mm=X2_mm,
        dists=[d1, d2, d3],
        cross_type='hbeam',
    )
