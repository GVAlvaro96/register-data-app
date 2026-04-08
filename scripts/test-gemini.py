import os
from dotenv import load_dotenv
from google import genai

# 1. Forzar la lectura del archivo .env para que encuentre tu GEMINI_API_KEY
load_dotenv()

# 2. Inicializar el cliente moderno de Google (lee la clave automáticamente)
try:
    client = genai.Client()
    print("✅ Cliente inicializado correctamente.")
    
    # 3. Hacer una petición rápida de prueba al modelo más rápido (Flash)
    print("⏳ Preguntando a Gemini...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Hola, dime en una sola frase corta que estás conectado y funcionando.'
    )
    
    print("\n🎉 ¡ÉXITO! Respuesta de Gemini:")
    print(f"🤖: {response.text}")

except Exception as e:
    print(f"\n❌ Error al conectar con la API: {e}")