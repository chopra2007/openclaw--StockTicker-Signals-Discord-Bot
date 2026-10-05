export function GET() {
  return new Response('{"component":"member-dashboard-frontend"}', {
    headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
  });
}
