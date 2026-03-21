-- 1. Los "Dueños" del sistema
CREATE TABLE negocios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_negocio VARCHAR(100) NOT NULL,
    zona_horaria VARCHAR(50) DEFAULT 'Europe/Madrid', -- CRÍTICO para Google Calendar
    google_refresh_token TEXT, -- Para mantener la conexión con su Calendar abierta
    plan_suscripcion VARCHAR(20) DEFAULT 'FREE',
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. El Catálogo de Servicios de cada negocio
CREATE TABLE servicios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    negocio_id UUID REFERENCES negocios(id) ON DELETE CASCADE,
    nombre VARCHAR(100) NOT NULL,
    duracion_minutos INTEGER NOT NULL DEFAULT 60,
    precio DECIMAL(10, 2), -- Por si en el futuro quieres añadir pasarela de pago (Stripe)
    activo BOOLEAN DEFAULT TRUE
);

-- 3. Los Pacientes
CREATE TABLE pacientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    negocio_id UUID REFERENCES negocios(id) ON DELETE CASCADE,
    telefono VARCHAR(20) NOT NULL,
    nombre VARCHAR(100),
    UNIQUE(negocio_id, telefono) 
);

-- 4. Las Citas (El corazón transaccional)
CREATE TABLE citas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    negocio_id UUID REFERENCES negocios(id) ON DELETE CASCADE,
    paciente_id UUID REFERENCES pacientes(id) ON DELETE CASCADE,
    servicio_id UUID REFERENCES servicios(id) ON DELETE RESTRICT, -- RESTRICT: No deja borrar un servicio si tiene citas
    fecha_hora TIMESTAMP WITH TIME ZONE NOT NULL,
    estado VARCHAR(20) DEFAULT 'CONFIRMADA', -- CONFIRMADA, CANCELADA, REALIZADA
    calendar_event_id VARCHAR(255), -- El ID que nos devolverá Google Calendar
    notas TEXT, -- Por si el paciente dice "Me duele mucho el hombro" por WhatsApp
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Restricción básica: Un negocio no puede tener dos citas a la misma hora exacta
    UNIQUE (negocio_id, fecha_hora) 
);