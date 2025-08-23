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
    file \
    git \
    procps \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Tamarin dependencies
RUN apt-get update && apt-get install -y \
    graphviz maude haskell-stack \
    libgmp-dev libffi-dev zlib1g-dev libtinfo-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Solidity compiler
RUN add-apt-repository ppa:ethereum/ethereum \
    && apt-get update \
    && apt-get install -y solc \
    && rm -rf /var/lib/apt/lists/*

# Clone and build Tamarin prover
RUN git clone https://github.com/tamarin-prover/tamarin-prover.git /opt/tamarin

WORKDIR /opt/tamarin
RUN stack setup && stack build && stack install
ENV PATH="/root/.local/bin:$PATH"
RUN stack clean --full && rm -rf /root/.stack /opt/tamarin
WORKDIR /app

# Install Circom compiler and circomspect analyzer
RUN npm install -g circom && cargo install circomspect

# Install OpenZeppelin contracts
RUN npm init -y && npm install @openzeppelin/contracts

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Copy application
COPY main.py .

EXPOSE 8080

CMD ["python3", "main.py"]
