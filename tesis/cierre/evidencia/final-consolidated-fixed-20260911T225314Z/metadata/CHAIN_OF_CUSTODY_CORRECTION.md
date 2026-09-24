# Corrección de cadena de custodia

La comprobación independiente inicial buscó el commit temporal en el repositorio original. Ese supuesto era incorrecto: el commit identifica al repositorio temporal congelado, no a la base de objetos original.

Se agregó un bundle Git autocontenido y un archive determinista. Ambos se verificaron desde cero contra el commit, tree y manifiesto de archivos ya asociados a la corrida. No se repitió ninguna prueba ni se alteró un resultado.
