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

# Install a released GHC via ghcup and build Tamarin with the system GHC
RUN curl --proto '=https' --tlsv1.2 -sSf https://get-ghcup.haskell.org | \
        BOOTSTRAP_HASKELL_NONINTERACTIVE=1 BOOTSTRAP_HASKELL_YES=1 BOOTSTRAP_HASKELL_MINIMAL=1 sh && \
    /root/.ghcup/bin/ghcup install ghc 9.6.5 && \
    /root/.ghcup/bin/ghcup set ghc 9.6.5
ENV PATH="/root/.ghcup/bin:$PATH"
# Use the installed GHC to build Tamarin and avoid missing configure script errors
RUN stack update && \
    stack --system-ghc --no-install-ghc --resolver lts-22.0 setup && \
    stack --system-ghc --no-install-ghc --resolver lts-22.0 build && \
    stack --system-ghc --no-install-ghc --resolver lts-22.0 install
ENV PATH="/root/.ghcup/bin:/root/.local/bin:$PATH"
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
