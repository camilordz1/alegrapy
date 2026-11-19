# Excepciones

Jerarquía de errores de la librería. Todas las clases heredan de `AlegraAPIError`, por lo que
`except AlegraAPIError` captura cualquier fallo de la API o del transporte. Ver también la guía de
[errores](../guias/errores.md).

::: alegra.exceptions.AlegraAPIError

::: alegra.exceptions.AlegraAuthError

::: alegra.exceptions.AlegraNotFoundError

::: alegra.exceptions.AlegraValidationError

::: alegra.exceptions.AlegraRateLimitError

::: alegra.exceptions.AlegraServerError

::: alegra.exceptions.AlegraConnectionError

::: alegra.exceptions.AlegraTimeoutError

::: alegra.exceptions.AlegraUnverifiedCreateError
