# Excepciones

Jerarquía de errores de la librería. Todas las clases heredan de `AlegraAPIError`, por lo que
`except AlegraAPIError` captura cualquier fallo de la API o del transporte. Ver también la guía de
[errores](../guias/errores.md).

::: alegrapy.exceptions.AlegraAPIError

::: alegrapy.exceptions.AlegraAuthError

::: alegrapy.exceptions.AlegraNotFoundError

::: alegrapy.exceptions.AlegraValidationError

::: alegrapy.exceptions.AlegraRateLimitError

::: alegrapy.exceptions.AlegraServerError

::: alegrapy.exceptions.AlegraConnectionError

::: alegrapy.exceptions.AlegraTimeoutError

::: alegrapy.exceptions.AlegraFileNotAvailableError

::: alegrapy.exceptions.AlegraStampError

::: alegrapy.exceptions.AlegraAlreadyAnnulledError

::: alegrapy.exceptions.AlegraUnverifiedCreateError
