# HOSTELERIA

## Descripción
HOSTELERIA es un sistema diseñado para la gestión de operaciones en un entorno hostelero. Este proyecto incluye módulos para la gestión de habitaciones, finanzas, autenticación y más.

## Estructura del Proyecto
El proyecto está organizado en las siguientes carpetas principales:

- **database/**: Contiene la conexión a la base de datos y los modelos.
- **modules/**: Incluye módulos específicos como:
  - **auth/**: Gestión de autenticación y login.
  - **finance/**: Gestión financiera, incluyendo apertura de caja, cargos extra, y cierre de turnos.
  - **rooms/**: Gestión de habitaciones, check-in, check-out y detalles.
- **utils/**: Utilidades generales como validadores y cálculos financieros.
- **assets/**: Archivos estáticos y recursos adicionales.

## Archivos Clave
- **main.py**: Punto de entrada principal del sistema.
- **requirements.txt**: Lista de dependencias necesarias para ejecutar el proyecto.
- **setup.py**: Configuración para la instalación del proyecto.

## Instalación
1. Clona este repositorio:
   ```bash
   git clone https://github.com/reidchend/HOSTELERIA.git
   ```
2. Navega al directorio del proyecto:
   ```bash
   cd HOSTELERIA
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## Uso
Ejecuta el archivo principal para iniciar el sistema:
```bash
python main.py
```

## Contribución
1. Crea un fork del repositorio.
2. Crea una nueva rama para tus cambios:
   ```bash
   git checkout -b feature/nueva-funcionalidad
   ```
3. Realiza tus cambios y súbelos:
   ```bash
   git commit -m "Descripción de los cambios"
   git push origin feature/nueva-funcionalidad
   ```
4. Abre un Pull Request en GitHub.

## Licencia
Este proyecto está bajo la licencia MIT. Consulta el archivo `LICENSE` para más detalles.