## MODIFIED Requirements

### Requirement: Validación de pattern, severity y action

El sistema SHALL validar todo `pattern` recibido como un glob compatible con `fnmatch` de Python (RN-08, RN-58) y como una ruta bien formada (D91/RN-185). Descontado el prefijo de negación `!`, el `pattern` MUST: no ser vacío ni sólo espacios; empezar con `/`; no contener un segmento `..`; no contener caracteres de control (U+0000–U+001F y U+007F); medir a lo sumo 1.024 caracteres (contando el `!`); y ser un glob bien formado, donde todo `[` abre una clase que se cierra con `]` según la regla de clases de `fnmatch.translate` (`[]...]` y `[!...]` son válidos). Un `pattern` igual al de otra regla MUST rechazarse. Cada rechazo de `pattern` MUST responder `422` con `detail` `{"code": <código>, "message": <texto en español>}` (D90/RN-184), con los códigos `pattern_empty`, `pattern_not_absolute`, `pattern_parent_segment`, `pattern_control_char`, `pattern_too_long`, `pattern_invalid_glob` y `pattern_duplicate`, evaluados en ese orden. El `severity` MUST pertenecer al enum `RuleSeverity` (critical, high, medium, low) y el `action` al enum `RuleAction` (auto_restore, quarantine, manual_review, alert_only); valores fuera del enum MUST ser rechazados con 422. La validación MUST ocurrir antes de cualquier escritura en base de datos, incremento de `ruleset_version` o publicación de `rule_sync`, tanto en `POST /rules` como en `PUT /rules/{id}`. Las reglas ya persistidas MUST NOT revalidarse al leerlas ni al evaluarlas.

#### Scenario: Pattern inválido
- **WHEN** un admin hace `POST /rules` con `pattern` vacío o un glob no compilable
- **THEN** el sistema retorna 422 y no persiste nada ni incrementa el counter

#### Scenario: Pattern relativo
- **WHEN** un admin hace `POST /rules` con `pattern="relative/path"`
- **THEN** el sistema retorna 422 con `detail.code == "pattern_not_absolute"` y un `detail.message` en español
- **AND** no persiste nada ni incrementa `ruleset_version`

#### Scenario: Pattern negado se valida sin el prefijo
- **WHEN** un admin hace `POST /rules` con `pattern="!/var/log/*.log"`
- **THEN** el sistema retorna 201
- **AND** con `pattern="!tmp/*"` retorna 422 con `detail.code == "pattern_not_absolute"`

#### Scenario: Segmento de directorio padre
- **WHEN** un admin hace `POST /rules` con `pattern="/etc/../../etc/passwd"` o `pattern="/../../etc/passwd"`
- **THEN** el sistema retorna 422 con `detail.code == "pattern_parent_segment"`
- **AND** `pattern="/etc/a..b"` es aceptado (`..` no es un segmento)

#### Scenario: Caracteres de control
- **WHEN** un admin hace `POST /rules` con un `pattern` que contiene `\n`, `\t` o `\x00`
- **THEN** el sistema retorna 422 con `detail.code == "pattern_control_char"`

#### Scenario: Pattern demasiado largo
- **WHEN** un admin hace `POST /rules` con un `pattern` absoluto de 1.025 caracteres
- **THEN** el sistema retorna 422 con `detail.code == "pattern_too_long"`
- **AND** un `pattern` absoluto de 1.024 caracteres es aceptado

#### Scenario: Clase de caracteres sin cerrar
- **WHEN** un admin hace `POST /rules` con `pattern="/etc/["`
- **THEN** el sistema retorna 422 con `detail.code == "pattern_invalid_glob"`
- **AND** `pattern="/etc/[abc]*.conf"` y `pattern="/etc/[!.]*"` son aceptados

#### Scenario: Pattern duplicado
- **WHEN** un admin hace `POST /rules` con un `pattern` igual al de una regla existente
- **THEN** el sistema retorna 422 con `detail.code == "pattern_duplicate"`

#### Scenario: La edición valida igual que el alta
- **WHEN** un admin hace `PUT /rules/{id}` con `pattern="../x"`
- **THEN** el sistema retorna 422 con `detail.code == "pattern_not_absolute"`
- **AND** la regla conserva su `pattern` anterior y `ruleset_version` no cambia

#### Scenario: Severity fuera del enum
- **WHEN** un admin hace `POST /rules` con `severity` que no está en {critical, high, medium, low}
- **THEN** el sistema retorna 422

#### Scenario: Action fuera del enum
- **WHEN** un admin hace `POST /rules` con `action` que no está en {auto_restore, quarantine, manual_review, alert_only}
- **THEN** el sistema retorna 422
