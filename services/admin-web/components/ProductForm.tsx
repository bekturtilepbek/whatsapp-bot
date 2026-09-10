"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createProduct, updateProduct, type Product, type ProductInput } from "@/lib/api";

interface ProductFormProps {
  botId: string;
  apiBaseUrl: string;
  /** Если задан — режим редактирования, иначе — создание нового товара. */
  product?: Product;
}

interface FormState {
  name: string;
  price: string;
  sku: string;
  description: string;
  displayOverride: boolean;
  showName: boolean;
  showDescription: boolean;
  showPrice: boolean;
}

function initialState(product: Product | undefined): FormState {
  const hasOverride = !!product && Object.keys(product.display_custom).length > 0;
  return {
    name: product?.name ?? "",
    price: product?.price ?? "",
    sku: product?.sku ?? "",
    description: product?.description ?? "",
    displayOverride: hasOverride,
    showName: product?.display_custom.show_name ?? true,
    showDescription: product?.display_custom.show_description ?? true,
    showPrice: product?.display_custom.show_price ?? true,
  };
}

function toInput(state: FormState): ProductInput {
  return {
    name: state.name.trim(),
    price: state.price.trim() === "" ? null : Number(state.price),
    sku: state.sku.trim() === "" ? null : state.sku.trim(),
    description: state.description.trim() === "" ? null : state.description.trim(),
    display_custom: state.displayOverride
      ? {
          show_name: state.showName,
          show_description: state.showDescription,
          show_price: state.showPrice,
        }
      : {},
  };
}

export function ProductForm({ botId, apiBaseUrl, product }: ProductFormProps) {
  const router = useRouter();
  const [state, setState] = useState<FormState>(() => initialState(product));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // PATCH на бэкенде мержит поля: null/пропуск значит «не трогать», а не
  // «очистить» (см. аналогичное поведение bots.image_prompt/pdf_prompt).
  // Значит стереть цену/артикул/описание обратно в пустоту через эту форму
  // нельзя — предупреждаем об этом в режиме редактирования там, где у товара
  // уже есть значение поля. Берём исходное значение из product, а не из
  // текущего state — подсказка не должна пропадать в момент, когда админ
  // как раз стирает поле (самый нужный момент её увидеть).
  const clearHint = "Поле нельзя очистить обратно — здесь можно только заменить значение на другое.";
  const showPriceHint = !!product && !!product.price && product.price.trim() !== "";
  const showSkuHint = !!product && !!product.sku && product.sku.trim() !== "";
  const showDescriptionHint = !!product && !!product.description && product.description.trim() !== "";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state.name.trim() === "") {
      setError("Название обязательно");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const input = toInput(state);
      if (product) {
        await updateProduct(apiBaseUrl, botId, product.id, input);
      } else {
        await createProduct(apiBaseUrl, botId, input);
      }
      router.push(`/bots/${botId}/products`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    // noValidate — та же причина, что и в BotSettingsForm: нативная
    // HTML5-валидация (required/min) тихо блокирует submit ДО нашей проверки.
    <form noValidate onSubmit={(e) => void handleSubmit(e)}>
      <label>
        Название
        <input
          type="text"
          value={state.name}
          onChange={(e) => setState({ ...state, name: e.target.value })}
        />
      </label>
      <label>
        Цена
        <input
          type="number"
          min={0}
          step={0.01}
          value={state.price}
          onChange={(e) => setState({ ...state, price: e.target.value })}
        />
      </label>
      {showPriceHint && (
        <p style={{ color: "gray", fontSize: "0.85em" }}>{clearHint}</p>
      )}
      <label>
        Артикул (SKU)
        <input
          type="text"
          value={state.sku}
          onChange={(e) => setState({ ...state, sku: e.target.value })}
        />
      </label>
      {showSkuHint && (
        <p style={{ color: "gray", fontSize: "0.85em" }}>{clearHint}</p>
      )}
      <label>
        Описание
        <textarea
          rows={4}
          value={state.description}
          onChange={(e) => setState({ ...state, description: e.target.value })}
        />
      </label>
      {showDescriptionHint && (
        <p style={{ color: "gray", fontSize: "0.85em" }}>{clearHint}</p>
      )}
      <label>
        <input
          type="checkbox"
          checked={state.displayOverride}
          onChange={(e) => setState({ ...state, displayOverride: e.target.checked })}
        />
        Переопределить вывод для этого товара
      </label>
      {state.displayOverride && (
        <fieldset>
          <label>
            <input
              type="checkbox"
              checked={state.showName}
              onChange={(e) => setState({ ...state, showName: e.target.checked })}
            />
            Показывать название
          </label>
          <label>
            <input
              type="checkbox"
              checked={state.showDescription}
              onChange={(e) => setState({ ...state, showDescription: e.target.checked })}
            />
            Показывать описание
          </label>
          <label>
            <input
              type="checkbox"
              checked={state.showPrice}
              onChange={(e) => setState({ ...state, showPrice: e.target.checked })}
            />
            Показывать цену
          </label>
        </fieldset>
      )}
      <button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </button>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
    </form>
  );
}
