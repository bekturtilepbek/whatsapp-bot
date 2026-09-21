"use client";

import { useCallback, useState } from "react";

/** Общий паттерн визуальной обратной связи для required-полей: красная
 * рамка + одноразовая shake-анимация на неудачном submit (globals.css
 * .animate-shake). shakeKey растёт на каждый вызов shake() — вызывающий
 * компонент включает его в React key обёртки поля, чтобы анимация
 * перезапускалась даже если невалидным снова оказалось то же самое поле
 * (просто смена className на тот же класс анимацию не перезапустит). */
export function useInvalidShake() {
  const [invalidFields, setInvalidFields] = useState<Set<string>>(new Set());
  const [shakeKey, setShakeKey] = useState(0);

  const shake = useCallback((fields: string[]) => {
    setInvalidFields(new Set(fields));
    setShakeKey((k) => k + 1);
  }, []);

  const clear = useCallback((field: string) => {
    setInvalidFields((current) => {
      if (!current.has(field)) {
        return current;
      }
      const next = new Set(current);
      next.delete(field);
      return next;
    });
  }, []);

  const isInvalid = useCallback((field: string) => invalidFields.has(field), [invalidFields]);

  return { shake, clear, isInvalid, shakeKey };
}
