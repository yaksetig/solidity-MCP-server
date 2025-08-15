FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    python3 \
    python3-pip \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Install Solidity compiler
RUN add-apt-repository ppa:ethereum/ethereum \
    && apt-get update \
    && apt-get install -y solc \
    && rm -rf /var/lib/apt/lists/*

# Install Slither
RUN pip3 install slither-analyzer

WORKDIR /app
COPY package*.json ./
RUN npm install --production

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
