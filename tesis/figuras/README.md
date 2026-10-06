# Figuras de la tesis

Fuentes de los diagramas del documento a partir de la versión 30. Cada PNG se
regenera desde su fuente; no editar los PNG a mano.

| Figura | Fuente | Contenido |
|---|---|---|
| 1 | `fig1.dot` | Arquitectura general y distribución física |
| 2 | `fig2.dot` | Modelo entidad-relación (generado desde los modelos SQLModel de v5.1-tesis) |
| 3 | `fig3.dot` | Flujo de procesamiento del agente |
| 4 | `fig4.mmd` | Diagrama de secuencia del protocolo de entrega |
| 5 | `fig5.dot` | Máquina de estados del evento |
| 8 | `fig8.dot` | Cascada de notificación |
| 9 | `fig9.dot` | Diagrama de despliegue UML |
| 10 | `fig10.dot` | Organización interna de componentes |

Las Figuras 6 y 7 son capturas de pantalla de la consola y no tienen fuente.

## Regenerar

Graphviz (Figuras 1, 2, 3, 5, 8, 9 y 10); la resolución (300 dpi) está fijada
en cada archivo:

```bash
for f in fig1 fig2 fig3 fig5 fig8 fig9 fig10; do dot -Tpng "$f.dot" -o "$f.png"; done
```

Mermaid (Figura 4), con `@mermaid-js/mermaid-cli`:

```bash
mmdc -i fig4.mmd -o fig4.png -w 1000 -s 3 -b white
```

Si cambia el esquema de la base de datos, la Figura 2 debe regenerarse a partir
de los modelos de `backend/app/modules/*/models.py`, no editando el `.dot`.
