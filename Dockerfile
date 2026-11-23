# The plug-in as a container, for catalogs and operators that run MCP servers that way. It needs nothing beyond
# Python's standard library, it speaks the Model Context Protocol over standard input and output, and it only reads
# the public files of https://check.loopholetape.com/ over the network.
FROM python:3.12-slim
WORKDIR /app
COPY mcp_server.py mcp_http.py ./
USER 65534:65534
ENTRYPOINT ["python3", "mcp_server.py"]
