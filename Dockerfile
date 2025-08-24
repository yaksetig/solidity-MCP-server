FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    nodejs \
    npm \
    software-properties-common \
    cargo \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Solidity compiler
RUN add-apt-repository ppa:ethereum/ethereum \
    && apt-get update \
    && apt-get install -y solc \
    && rm -rf /var/lib/apt/lists/*

# Install Slither for Solidity security analysis
RUN pip3 install slither-analyzer

WORKDIR /app

# Install Circom compiler and circomspect analyzer
RUN npm install -g circom && cargo install circomspect

# Install OpenZeppelin contracts
RUN npm init -y && npm install @openzeppelin/contracts

# Install Python dependencies
RUN pip3 install \
    fastapi==0.104.1 \
    uvicorn[standard]==0.24.0

# Copy application
COPY main.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Expose port
EXPOSE 8080

# Run the application
CMD ["python3", "main.py"]
