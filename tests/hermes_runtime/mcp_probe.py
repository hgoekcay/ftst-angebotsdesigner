"""Run inside the pinned Hermes image; negotiate MCP over a real subprocess pipe."""
import asyncio
import sys

from mcp import Client, StdioServerParameters


async def probe():
    server = StdioServerParameters(command=sys.executable, args=['/opt/ftst/atlas_tasks_mcp.py'])
    async with Client(server) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}
        assert names == {'atlas_task_create', 'atlas_tasks_list', 'atlas_task_get'}, names
        print('ATLAS MCP stdio: initialize and tools/list passed')


if __name__ == '__main__':
    asyncio.run(asyncio.wait_for(probe(), timeout=30))
