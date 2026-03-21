# 📅 Register Data App (SaaS Multi-Tenant)

## 🎯 Propósito del Proyecto
**Register Data App** es un sistema transaccional de gestión de citas automatizado, diseñado inicialmente para clínicas de fisioterapia, pero escalable a múltiples negocios (arquitectura multi-tenant). 

El objetivo es eliminar la gestión manual de citas a través de chats y unificarlas en un flujo automatizado utilizando un bot de WhatsApp, sincronización bidireccional con Google Calendar y una base de datos robusta, todo ello bajo una arquitectura orientada al coste cero (0€).

## 🏗️ Arquitectura y Stack Tecnológico
Este proyecto sigue un enfoque *API-First* y *Serverless* (para producción), manteniendo un entorno local en contenedores para el desarrollo.

* **Base de Datos:** PostgreSQL (Docker para desarrollo local / Supabase para producción).
* **Backend:** Python con FastAPI (Próximamente).
* **Integraciones Externas:**
  * WhatsApp Cloud API (Meta) para la interacción con el paciente.
  * Google Calendar API para la sincronización de agenda del profesional.
* **Capa Analítica:** Looker Studio para visualización de KPIs del negocio.
* **Infraestructura Local:** Docker & Docker Compose.

## 🗄️ Modelo de Datos (Multi-Tenant)
El sistema utiliza una arquitectura de **esquema compartido (Column-based multi-tenancy)**. Todas las entidades (`pacientes`, `citas`) están fuertemente vinculadas a un `negocio_id` específico, garantizando el aislamiento lógico de los datos entre diferentes clientes (ej. el fisioterapeuta no puede ver los datos del dentista).

## 🚀 Despliegue Local (Quick Start)
Para levantar el entorno de desarrollo en cualquier máquina:

1. **Clonar el repositorio:**
   ```bash
   git clone [https://github.com/TU_USUARIO/register_data_app.git](https://github.com/TU_USUARIO/register_data_app.git)
   cd register_data_app

2. **Levantar la infraestructura de datos:**
  ```bash
  docker-compose up -d
  * Esto levantará el contenedor de PostgreSQL y un cliente SQL web (Adminer) accesible desde http://localhost:8080.
