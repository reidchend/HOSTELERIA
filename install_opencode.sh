#!/bin/bash

# 1. Colores para la terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}>>> Iniciando instalación de OpenCode en Codespaces...${NC}"

# 2. Verificar e instalar Node.js/NPM si es necesario
if ! command -v npm &> /dev/null; then
    echo -e "${BLUE}Instalando Node.js...${NC}"
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

# 3. Instalar OpenCode de forma global
echo -e "${BLUE}Instalando OpenCode-AI...${NC}"
sudo npm install -g opencode-ai

# 4. Configurar el Token de GitHub para el agente
echo -e "${BLUE}Vinculando GITHUB_TOKEN de Codespaces...${NC}"
export GITHUB_TOKEN=$(gh auth token)

# Hacer que el token sea permanente en esta sesión de bash
if ! grep -q "GITHUB_TOKEN" ~/.bashrc; then
    echo 'export GITHUB_TOKEN=$(gh auth token)' >> ~/.bashrc
fi

echo -e "${GREEN} Successfully installed!${NC}"
echo -e "Para iniciar el agente en este proyecto, usa: ${BLUE}opencode .${NC}"
echo -e "Para usar la interfaz Web, usa: ${BLUE}opencode web${NC}"

# 5. Ejecutar la primera verificación
opencode --version
