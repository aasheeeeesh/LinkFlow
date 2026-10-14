import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

/** Keep page URLs clean when a full URL is pasted; the API does the authoritative normalisation. */
export function tidyQuery(raw: string): string {
  return raw
    .trim()
    .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
    .split(/[/?#]/, 1)[0]
    .replace(/^[^@]*@/, "")
    .replace(/:\d+$/, "")
    .replace(/\.$/, "");
}

export function SearchBox({ initial = "", autoFocus = false }: { initial?: string; autoFocus?: boolean }) {
  const [value, setValue] = useState(initial);
  const navigate = useNavigate();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const d = tidyQuery(value);
    if (d) navigate(`/domain/${encodeURIComponent(d)}`);
  };
  return (
    <form className="search" role="search" onSubmit={submit}>
      <label htmlFor="domain-search" className="visually-hidden">
        Domain name
      </label>
      <input
        id="domain-search"
        type="search"
        placeholder="example.com"
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button type="submit" className="primary">
        Look up
      </button>
    </form>
  );
}
