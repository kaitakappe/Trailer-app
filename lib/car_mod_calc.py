import math

def calc_braking_force(W, Wf, passenger_car=True):
    coeff = 0.65 if passenger_car else 0.5
    return coeff * (W + Wf) * 9.8

def check_strength(stress, allowable_stress):
    return allowable_stress / stress if stress != 0 else math.inf

def calc_stability_angle(cg_height, track_width):
    if cg_height <= 0:
        return 0.0
    return math.degrees(math.atan((track_width/2) / cg_height))
