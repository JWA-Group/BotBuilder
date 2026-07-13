from typing import Optional



from fastapi import Depends, Query



# Локальное desktop-приложение — один пользователь без входа в аккаунт.

DEFAULT_USER_ID = 1





async def get_current_user_id(

    user_id: Optional[int] = Query(None, description="ID пользователя (опционально)"),

) -> int:

    """

    Локальный режим: query user_id или DEFAULT_USER_ID.

    Старые JWT из localStorage больше не переопределяют пользователя.

    """

    if user_id is not None:

        return user_id

    return DEFAULT_USER_ID





async def get_current_user_id_required(

    user_id: int = Depends(get_current_user_id),

) -> int:

    return user_id

