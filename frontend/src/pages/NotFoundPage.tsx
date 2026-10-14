import { Link } from "react-router-dom";
import { usePageTitle } from "../usePageTitle";

export function NotFoundPage() {
  usePageTitle("Page not found");
  return (
    <>
      <h1>Page not found</h1>
      <p>
        There is no page at this address. Go to the <Link to="/">domain lookup</Link> or the{" "}
        <Link to="/playground">playground</Link>.
      </p>
    </>
  );
}
