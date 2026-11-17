import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

type PasswordFieldProps = {
  id: string;
  label: string;
  autoComplete: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
};

export function PasswordField({ id, label, autoComplete, required = true, minLength, maxLength }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="field-group">
      <label className="field-label" htmlFor={id}>{label}</label>
      <div className="password-wrap">
        <input className="field-input" id={id} name={id} type={visible ? "text" : "password"} autoComplete={autoComplete} required={required} minLength={minLength} maxLength={maxLength} />
        <button className="password-toggle" type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? "Ocultar senha" : "Mostrar senha"}>
          {visible ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div>
    </div>
  );
}
