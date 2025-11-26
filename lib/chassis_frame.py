import math

def compute_chassis_frame_strength(L_mm, point_loads, positions_mm, w_per_m, B_mm, H_mm, b_mm, h_mm, tb, ty):
    """計算: 単純支持梁 (支持点: 端A(0), 端B(L))
    L_mm: 梁全長 [mm]
    point_loads: 荷重値リスト [kg] 下向き正 (負で上向き反力等)
    positions_mm: 荷重位置リスト [mm] (0<L_i<L)
    w_per_m: 等分布荷重 [kg/m] (積載物自重等)
    断面寸法: 外形 B,H と 中抜き b,h
    tb, ty: 引張強さ / 降伏点 [kg/cm^2]

    戻り値 dict:
      RA,RB: 支点反力 [kg]
      shear: [(x, V)] せん断力分布 (kg)
      moment: [(x, M)] 曲げモーメント分布 (kg*cm)
      Mmax: 最大曲げ (kg*cm)
      Z_cm3: 断面係数 (cm^3)
      sigma: 曲げ応力 (kg/cm^2)
      sf_break, sf_yield, ok_break, ok_yield
    """
    if L_mm <= 0:
        raise ValueError('全長L_mm>0が必要')
    if len(point_loads) != len(positions_mm):
        raise ValueError('荷重数と位置数が一致しません')
    L = L_mm / 1000.0  # m
    # 検証
    for x in positions_mm:
        if not (0 < x < L_mm):
            raise ValueError('荷重位置は0とLの間(mm)')
    # 合計荷重
    Pw = w_per_m * L  # 等分布総荷重 (kg)
    P_points = sum(point_loads)
    # 反力計算
    # RA + RB = P_points + Pw
    # モーメント釣り合い (Aまわり): RB*L = Σ(Pi*xi_m) + Pw*L/2
    xi_m = [x/1000.0 for x in positions_mm]
    RB = (sum(p*x for p,x in zip(point_loads, xi_m)) + Pw * L/2.0) / L
    RA = P_points + Pw - RB
    # せん断力 & モーメント分布 (離散: 支点 + 荷重点 + 終端)
    x_points = [0.0] + xi_m + [L]
    # ソート (念のため)
    x_points = sorted(set(x_points))
    shear_list = []
    moment_list = []
    V = RA  # 左端直後のせん断
    last_x = 0.0
    # 分布荷重の寄与: 区間ΔxでVは w_per_m*Δx だけ減少
    for xp in x_points[1:]:
        dx = xp - last_x
        # 分布荷重によるせん断減少
        V -= w_per_m * dx
        # 荷重がこの位置にあれば追加減少
        for p,xm in zip(point_loads, xi_m):
            if abs(xp - xm) < 1e-9:
                V -= p
        # 曲げモーメント: 区間内線形 → 端での値を積分簡易で求める
        # ここでは端でのモーメント M(xp) を再帰的に求める: M'(x)=V(x)
        # シンプルに台形近似で積分
        # 直前せん断 V_prev は最後の更新前を再構成
        # ためにステップごとに記録
        shear_list.append((xp, V))
        last_x = xp
    # モーメント分布再計算精密: 走査し微小区間台形積分
    # まず全イベント点に対し区間内平均せん断で増分
    events = [0.0] + [x for x in xi_m] + [L]
    events = sorted(events)
    V_current = RA
    M = 0.0
    moment_list.append((0.0, M))
    prev = 0.0
    for nxt in events[1:]:
        dx = nxt - prev
        # 分布荷重でせん断線形低下: V(x) = V_current - w_per_m*(x-prev)
        # モーメント増分 = ∫ V(x) dx = V_current*dx - (w_per_m*dx^2)/2
        M += V_current*dx - (w_per_m*dx*dx)/2.0
        moment_list.append((nxt, M))
        # 区間末端で分布荷重によるせん断減少
        V_current -= w_per_m*dx
        # もし点荷重
        for p,xm in zip(point_loads, xi_m):
            if abs(nxt - xm) < 1e-9:
                V_current -= p
        prev = nxt
    # 最終チェック (右端モーメント理論値 ~0) 簡易補正
    # 右端でM理論は ΣRA*x - Σ荷重*距離 - Pw*L^2/2 ≈ 0
    # わずかな数値誤差補正
    if moment_list[-1][0] < L:
        moment_list.append((L, M))
    # 最大曲げ
    Mmax = max(abs(m) for _,m in moment_list)
    # 断面係数 (中抜き矩形) Z = (B*H^3 - b*h^3)/(6*H) [mm^3]; mm→cm換算
    Z_mm3 = (B_mm*(H_mm**3) - b_mm*(h_mm**3))/(6.0*H_mm)
    Z_cm3 = Z_mm3 / 1000.0  # 1 cm^3 = 1000 mm^3
    # 曲げ応力 sigma = Mmax / Z  (注意: Mmax[kg*cm], Z[cm^3] → kg/cm^2)
    # moment_list の単位: M kg*cm (L,m→cm換算要注意)。今 M は kg*mから?
    # 現在 M は V[kg]×x[m] なので単位 kg*m. 1 m = 100 cm → kg*m = 100 kg*cm
    # 換算
    Mmax_cm = Mmax * 100.0
    sigma = Mmax_cm / Z_cm3 if Z_cm3 != 0 else float('inf')
    sf_break = tb / (2.5 * sigma) if sigma>0 else float('inf')
    sf_yield = ty / (2.5 * sigma) if sigma>0 else float('inf')
    return {
        'RA': RA,
        'RB': RB,
        'Pw': Pw,
        'P_points': P_points,
        'shear_points': shear_list,
        'moment_points': moment_list,
        'Mmax': Mmax_cm,
        'Z_cm3': Z_cm3,
        'sigma': sigma,
        'sf_break': sf_break,
        'sf_yield': sf_yield,
        'ok_break': sf_break>1.6,
        'ok_yield': sf_yield>1.3
    }
