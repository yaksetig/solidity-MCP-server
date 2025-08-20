FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    nodejs \
    npm \
    software-properties-common \
    nodejs \
    npm \
    cargo \
    && rm -rf /var/lib/apt/lists/*

# Install Solidity compiler
RUN add-apt-repository ppa:ethereum/ethereum \
    && apt-get update \
    && apt-get install -y solc \
    && rm -rf /var/lib/apt/lists/*

# Install Circom compiler and circomspect analyzer
RUN npm install -g circom && cargo install circomspect

WORKDIR /app

# Install OpenZeppelin contracts
RUN npm init -y && npm install @openzeppelin/contracts

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Copy application
COPY main.py .

EXPOSE 8080

CMD ["python3", "main.py"]
