"""Intervalo de Newcombe (1998), método 10, para la diferencia de
proporciones pareadas, con y sin la corrección de phi."""
from math import sqrt
from scipy.stats import norm

def wilson(x, n, z):
    p = x / n
    centro = p + z * z / (2 * n)
    margen = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    den = 1 + z * z / n
    return (centro - margen) / den, (centro + margen) / den

def newcombe10(a, b, c, d, corregir_phi=True, conf=0.95):
    n = a + b + c + d
    z = norm.ppf(1 - (1 - conf) / 2)
    p1, p2 = (a + b) / n, (a + c) / n          # artefacto, control
    l1, u1 = wilson(a + b, n, z)
    l2, u2 = wilson(a + c, n, z)
    margenes = [(a + b), (c + d), (a + c), (b + d)]
    if 0 in margenes:
        phi = 0.0                                # margen vacío
    else:
        num = a * d - b * c
        if corregir_phi:
            if num > 0:
                num = max(num - n / 2, 0)
            elif num < 0:
                num = min(num + n / 2, 0)
        phi = num / sqrt(margenes[0] * margenes[1] * margenes[2] * margenes[3])
    dif = p1 - p2
    dl = sqrt((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2)
    du = sqrt((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2)
    return dif - dl, dif + du

def mcnemar(b, c):
    from scipy.stats import chi2
    est = (abs(b - c) - 1) ** 2 / (b + c)
    return est, chi2.sf(est, 1)

# a: ambos; b: solo el artefacto; c: solo el control; d: ninguno
REPLICAS = {1: (72, 428, 0, 0), 2: (98, 397, 0, 5), 3: (94, 405, 0, 1)}
for r, (a, b, c, d) in REPLICAS.items():
    con = newcombe10(a, b, c, d, True)
    sin = newcombe10(a, b, c, d, False)
    est, p = mcnemar(b, c)
    print(f"Réplica {r}: con phi [{con[0]:.4f}; {con[1]:.4f}]  "
          f"sin phi [{sin[0]:.4f}; {sin[1]:.4f}]  "
          f"McNemar {est:.2f}; p = {p:.2e}")
