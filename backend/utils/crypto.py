# backend/utils/crypto.py
import hashlib
import secrets
import base64
from typing import Optional

class CryptoManager:
    """Менеджер для хеширования и проверки паролей"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Безопасное хеширование пароля с использованием PBKDF2.
        Не требует bcrypt.
        """
        # Генерируем случайную соль (32 байта)
        salt = secrets.token_bytes(32)
        
        # Используем PBKDF2 с SHA256 и 100,000 итераций
        key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000,  # Количество итераций (можно увеличить для большей безопасности)
            dklen=32  # Длина ключа
        )
        
        # Формат: base64(salt + key)
        combined = salt + key
        return base64.b64encode(combined).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, hashed_password: str) -> bool:
        """
        Проверка пароля против хеша.
        """
        try:
            # Декодируем из base64
            decoded = base64.b64decode(hashed_password)
            
            # Соль - первые 32 байта, ключ - следующие 32 байта
            salt = decoded[:32]
            stored_key = decoded[32:64]
            
            # Хешируем введенный пароль с той же солью
            key = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt,
                100000,
                dklen=32
            )
            
            # Сравниваем безопасным способом
            return secrets.compare_digest(key, stored_key)
        except Exception:
            return False

# Создаем экземпляр для импорта
crypto = CryptoManager()

# Экспортируем функции с совместимыми именами
hash_password = crypto.hash_password
verify_password = crypto.verify_password