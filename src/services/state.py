estados_conversacion = {}
datos_reserva = {}  # 🧠 NUEVO: Memoria para guardar el servicio que elija

def obtener_estado(telefono: str) -> str:
    return estados_conversacion.get(telefono, "INICIO")

def actualizar_estado(telefono: str, nuevo_estado: str):
    estados_conversacion[telefono] = nuevo_estado

# --- NUEVAS FUNCIONES PARA GUARDAR DATOS ---
def guardar_dato_reserva(telefono: str, clave: str, valor: any):
    if telefono not in datos_reserva:
        datos_reserva[telefono] = {}
    datos_reserva[telefono][clave] = valor

def obtener_dato_reserva(telefono: str, clave: str):
    return datos_reserva.get(telefono, {}).get(clave)

def limpiar_estado(telefono: str):
    if telefono in estados_conversacion:
        del estados_conversacion[telefono]
    if telefono in datos_reserva:
        del datos_reserva[telefono]