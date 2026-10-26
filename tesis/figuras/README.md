# Figuras de la tesis

Fuentes de los diagramas del documento a partir de la versión 30. Cada SVG y
cada PNG se regenera desde su fuente; no editarlos a mano.

| Figura | Fuente | Contenido |
|---|---|---|
| 1 | `fig1.dot` | Arquitectura general y distribución física |
| 2 | `fig2.dot` | Modelo entidad-relación (generado desde los modelos SQLModel de v5.1-tesis) |
| 3a | `fig3a.dot` | Flujo de procesamiento del agente: arranque y sincronización |
| 3b | `fig3b.dot` | Flujo de procesamiento del agente: operación continua |
| 4 | `fig4.mmd` | Diagrama de secuencia del protocolo de entrega |
| 5 | `fig5.dot` | Máquina de estados del evento |
| 8 | `fig8.dot` | Cascada de notificación |
| 9 | `fig9.dot` | Diagrama de despliegue UML |
| 10 | `fig10.dot` | Organización interna de componentes |

Las Figuras 6 y 7 son capturas de pantalla de la consola y no tienen fuente.

## SVG incrustados en el documento

El documento incrusta las Figuras 1 a 5 y 8 a 10 como SVG, con un PNG de
respaldo para los programas que no leen SVG. Los SVG incrustados son los
`figN.svg` de este directorio, y `scripts/verificar_medios.py` comprueba que
coincidan byte a byte con los del documento (Anexo F.1):

```bash
python3 scripts/verificar_medios.py tesis/entrega/<documento>.docx
# SVG incrustados: 8 (esperados 8); coinciden con tesis/figuras: 8
```

## Regenerar

Graphviz 2.43.0 (Figuras 1, 2, 3, 5, 8, 9 y 10), con la tipografía DejaVu
Sans que fija cada fuente. Con esa versión y esa tipografía, las órdenes
siguientes reproducen byte a byte los SVG versionados. Las Figuras 1, 2, 3, 5
y 8 se generaron con la resolución que fija cada archivo (300 dpi), y las
Figuras 9 y 10, con `-Gdpi=72`, como indica el Anexo L.6. La diferencia solo
cambia la escala del lienzo, no el dibujo, porque el documento ajusta cada
figura al ancho de la caja de texto:

```bash
for f in fig1 fig2 fig3a fig3b fig5 fig8; do dot -Tsvg:cairo "$f.dot" -o "$f.svg"; done
for f in fig9 fig10; do dot -Tsvg:cairo -Gdpi=72 "$f.dot" -o "$f.svg"; done
# PNG de respaldo, a 300 dpi
for f in fig1 fig2 fig3a fig3b fig5 fig8 fig9 fig10; do dot -Tpng "$f.dot" -o "$f.png"; done
```

Mermaid (Figura 4), con `@mermaid-js/mermaid-cli`:

```bash
mmdc -i fig4.mmd -o fig4.png -w 1000 -s 3 -b white
```

`fig4.svg` es el SVG que incrustaba el documento de la etiqueta
entrega-tesis-v9. No se reproduce byte a byte con `mmdc`: la salida de
mermaid-cli depende de su versión y del navegador que usa, y el SVG versionado
dibuja el texto como trazos. Se conserva como el archivo de referencia de la
Figura 4; si se modifica `fig4.mmd`, hay que regenerarlo y reemplazarlo en el
documento.

Si cambia el esquema de la base de datos, la Figura 2 debe regenerarse a partir
de los modelos de `backend/app/modules/*/models.py`, no editando el `.dot`.
