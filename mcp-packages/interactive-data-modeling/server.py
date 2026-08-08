def main() -> None:
    """Import the MCP server only in the actual STDIO parent process."""
    from shield_prediction_mcp.server import main as run_server

    run_server()


if __name__ == "__main__":
    main()
