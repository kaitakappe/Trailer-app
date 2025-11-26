import math

def calc_Lc(L2, l2, S):
    return math.sqrt(L2**2 + l2**2 + S**2)

def calc_R(L1, Lc, l1):
    return math.sqrt(L1**2 + (Lc + l1)**2)
