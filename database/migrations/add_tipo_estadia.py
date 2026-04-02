# database/migrations/add_tipo_estadia.py
"""
Migración para agregar campos de tipo estadía a la tabla stays.

Ejecutar con: python -m database.migrations.add_tipo_estadia
"""

from database.connection import SesionLocal, motor
from sqlalchemy import text


def run_migration():
    """Agrega las columnas tipo, horas_contratadas, costo_hora a stays."""
    with motor.connect() as conn:
        # Verificar si ya existen las columnas
        result = conn.execute(text("PRAGMA table_info(stays)"))
        columnas = [row[1] for row in result]
        
        if "tipo" not in columnas:
            conn.execute(text("ALTER TABLE stays ADD COLUMN tipo VARCHAR(20) DEFAULT 'noche'"))
            print("✅ Columna 'tipo' agregada")
        else:
            print("ℹ️  Columna 'tipo' ya existe")
        
        if "horas_contratadas" not in columnas:
            conn.execute(text("ALTER TABLE stays ADD COLUMN horas_contratadas INTEGER"))
            print("✅ Columna 'horas_contratadas' agregada")
        else:
            print("ℹ️  Columna 'horas_contratadas' ya existe")
        
        if "costo_hora" not in columnas:
            conn.execute(text("ALTER TABLE stays ADD COLUMN costo_hora NUMERIC(12,4) DEFAULT 20"))
            print("✅ Columna 'costo_hora' agregada")
        else:
            print("ℹ️  Columna 'costo_hora' ya existe")
        
        conn.commit()
    print("✅ Migración completada")


if __name__ == "__main__":
    run_migration()
