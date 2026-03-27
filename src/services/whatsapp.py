import httpx
from src.core.config import settings

async def enviar_mensaje_texto(telefono_destino: str, texto: str):
    """
    Envía un mensaje de texto simple a un paciente vía WhatsApp Cloud API.
    """
    url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "text",
        "text": {"body": texto}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"✅ Mensaje enviado a {telefono_destino}")
            return True
        except httpx.HTTPStatusError as e:
            print(f"❌ Error enviando mensaje a Meta: {e.response.text}")
            return False